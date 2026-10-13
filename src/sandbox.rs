//! Apply before parsing input or starting converter threads. No unsandboxed fallback.
use std::{
    ffi::CString,
    fs, io,
    os::unix::{
        ffi::OsStrExt,
        io::{AsRawFd, FromRawFd, OwnedFd},
    },
    path::Path,
};

#[repr(C)]
struct Ruleset {
    fs: u64,
    net: u64,
    scoped: u64,
}
#[repr(C, packed)]
struct PathRule {
    access: u64,
    fd: i32,
}
const READ_FILE: u64 = 1 << 2;
const READ_DIR: u64 = 1 << 3;
// Read/write regular files, directories, rename and truncate. No execution,
// device nodes, sockets, FIFOs, symlinks or device ioctls, even in scratch.
const WORK: u64 = READ_FILE
    | READ_DIR
    | (1 << 1)
    | (1 << 4)
    | (1 << 5)
    | (1 << 7)
    | (1 << 8)
    | (1 << 13)
    | (1 << 14);

fn checked(result: libc::c_long) -> io::Result<libc::c_long> {
    if result < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(result)
    }
}
fn allow(ruleset: &OwnedFd, path: &Path, access: u64) -> io::Result<()> {
    let name = CString::new(path.as_os_str().as_bytes())?;
    // O_PATH follows the trusted, canonicalized path, and does not open file contents.
    let fd = unsafe {
        OwnedFd::from_raw_fd(
            checked(libc::open(name.as_ptr(), libc::O_PATH | libc::O_CLOEXEC) as _)? as _,
        )
    };
    let rule = PathRule {
        access,
        fd: fd.as_raw_fd(),
    };
    unsafe {
        checked(libc::syscall(
            libc::SYS_landlock_add_rule,
            ruleset.as_raw_fd(),
            1,
            &rule,
            0,
        ))?;
    }
    Ok(())
}

/// The caller must be single threaded and pass trusted paths. Input must be
/// outside the private output directory. This function also closes inherited
/// capabilities (FDs >= 3); only stdin/stdout/stderr survive.
pub fn enter(input: &Path, output: &Path) -> Result<(), Box<dyn std::error::Error>> {
    unsafe {
        // Available on every upstream kernel supporting our minimum Landlock ABI.
        checked(libc::syscall(libc::SYS_close_range, 3u32, u32::MAX, 0u32)).map_err(|e| {
            format!("Preview sandbox unavailable: cannot close inherited descriptors ({e})")
        })?;
    }
    let abi = unsafe {
        checked(libc::syscall(
            libc::SYS_landlock_create_ruleset,
            std::ptr::null::<Ruleset>(),
            0usize,
            1u32,
        ))
    }
    .map_err(|e| format!("Preview sandbox unavailable: Landlock is required ({e})"))?;
    if abi < 3 {
        return Err("Preview sandbox requires Landlock ABI 3 or newer".into());
    }
    let input = fs::canonicalize(input)?;
    let work = fs::canonicalize(
        output
            .parent()
            .ok_or("Output requires a private parent directory")?,
    )?;
    let fonts = fs::canonicalize(
        std::env::var_os("DAVROS_PREVIEW_FONTS").ok_or("DAVROS_PREVIEW_FONTS is required")?,
    )?;
    let config = fs::canonicalize(
        std::env::var_os("FONTCONFIG_FILE").ok_or("FONTCONFIG_FILE is required")?,
    )?;
    if !input.is_file()
        || !fonts.is_dir()
        || !config.is_file()
        || !work.is_dir()
        || input.starts_with(&work)
        || fonts.starts_with(&work)
        || config.starts_with(&work)
        || work.starts_with(&fonts)
        || input.starts_with(&fonts)
    {
        return Err("Sandbox requires separate input, fonts and private output directory".into());
    }
    if output.extension().and_then(|s| s.to_str()) != Some("pdf") {
        return Err("Output must have a .pdf extension".into());
    }
    // Environment mutation is safe here: startup is single threaded. Font caches
    // and embedded-font extraction stay inside this job, never shared with others.
    unsafe {
        std::env::set_var("TMPDIR", &work);
        std::env::set_var("XDG_CACHE_HOME", work.join("cache"));
        checked(libc::prctl(libc::PR_SET_DUMPABLE, 0, 0, 0, 0) as _)?;
        checked(libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) as _)?;
    }
    let attr = Ruleset {
        fs: (1
            << if abi >= 9 {
                17
            } else if abi >= 5 {
                16
            } else {
                15
            })
            - 1,
        net: if abi >= 10 {
            15
        } else if abi >= 4 {
            3
        } else {
            0
        },
        scoped: if abi >= 6 { 3 } else { 0 },
    };
    let size = if abi >= 6 {
        24usize
    } else if abi >= 4 {
        16
    } else {
        8
    };
    let ruleset = unsafe {
        OwnedFd::from_raw_fd(checked(libc::syscall(
            libc::SYS_landlock_create_ruleset,
            &attr,
            size,
            0u32,
        ))? as _)
    };
    allow(&ruleset, &input, READ_FILE)?;
    allow(&ruleset, &fonts, READ_FILE | READ_DIR)?;
    allow(&ruleset, &config, READ_FILE)?;
    allow(&ruleset, &work, WORK)?;
    unsafe {
        checked(libc::syscall(
            libc::SYS_landlock_restrict_self,
            ruleset.as_raw_fd(),
            0u32,
        ))?;
    }
    if abi < 9 {
        eprintln!(
            "Preview sandbox: Landlock ABI {abi}; filesystem isolation active, socket/signal restrictions depend on kernel support (full configured policy requires ABI 9)."
        );
    }
    Ok(())
}
