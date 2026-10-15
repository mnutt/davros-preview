//! Best-effort process hardening, detected in the actual execution environment.
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

/// Results describe this process, not the host kernel in isolation. In
/// particular, an outer seccomp filter may deny an otherwise supported syscall.
#[derive(Debug)]
pub struct SecurityReport {
    pub landlock_abi: Option<i64>,
    pub features: Vec<(&'static str, bool, String)>,
}
impl SecurityReport {
    fn record(&mut self, name: &'static str, result: Result<String, String>) {
        let (enabled, detail) = match result {
            Ok(detail) => (true, detail),
            Err(detail) => {
                // Missing newer ABI capabilities are expected, and remain in
                // the structured report. Keep unexpected hardening failures visible.
                if name != "filesystem_isolation" && !detail.starts_with("requires ") {
                    eprintln!("Preview security unavailable: {name}: {detail}");
                }
                (false, detail)
            }
        };
        self.features.push((name, enabled, detail));
    }
}

fn unavailable(stage: &str, error: io::Error) -> String {
    let reason = match error.raw_os_error() {
        Some(libc::ENOSYS) => "syscall unavailable or hidden by an outer sandbox",
        Some(libc::EOPNOTSUPP) => "feature disabled or unsupported",
        Some(libc::EPERM | libc::EACCES) => "denied by permissions or an outer sandbox",
        _ => "operation failed",
    };
    format!("{stage}: {reason} ({error})")
}

fn close_inherited_fds() -> Result<String, String> {
    let range = unsafe { checked(libc::syscall(libc::SYS_close_range, 3u32, u32::MAX, 0u32)) };
    if range.is_ok() {
        return Ok("close_range".into());
    }
    // Startup is single threaded. Collect and drop ReadDir before closing any
    // descriptors, avoiding closing its own FD while the iterator still owns it.
    let fallback = || -> io::Result<()> {
        let mut fds = Vec::new();
        for entry in fs::read_dir("/proc/self/fd")? {
            let name = entry?.file_name();
            let fd: i32 = name
                .to_str()
                .and_then(|n| n.parse().ok())
                .ok_or_else(|| io::Error::other("invalid descriptor in /proc/self/fd"))?;
            if fd >= 3 {
                fds.push(fd);
            }
        }
        for fd in fds {
            if unsafe { libc::close(fd) } < 0 {
                let error = io::Error::last_os_error();
                // The ReadDir FD was closed when enumeration finished. Linux
                // also releases the FD on EINTR; retrying close is unsafe.
                if !matches!(error.raw_os_error(), Some(libc::EBADF | libc::EINTR)) {
                    return Err(error);
                }
            }
        }
        Ok(())
    };
    match fallback() {
        Ok(()) => Ok(format!(
            "/proc/self/fd fallback; {}",
            unavailable("close_range", range.unwrap_err())
        )),
        Err(error) => {
            // Sandstorm commonly has no /proc. Make a bounded cleanup attempt,
            // but do not claim completeness: inherited FDs may exceed today's
            // RLIMIT_NOFILE, and individual close calls may also be denied.
            for fd in 3..1_048_576 {
                unsafe {
                    libc::close(fd);
                }
            }
            Err(format!(
                "{}; {}; attempted individual closes below 1048576; exhaustive cleanup unverified",
                unavailable("close_range", range.unwrap_err()),
                unavailable("/proc/self/fd fallback", error)
            ))
        }
    }
}

fn process_flag(set: i32, get: i32, value: i32, label: &str) -> Result<String, String> {
    let set_result = unsafe { checked(libc::prctl(set, value, 0, 0, 0) as _) };
    // An outer sandbox may already enforce the desired value and deny changes.
    let observed = unsafe { libc::prctl(get, 0, 0, 0, 0) };
    if observed == value {
        return Ok("active (verified with prctl)".into());
    }
    if observed >= 0 {
        return Err(format!(
            "{label}: verification returned {observed}, expected {value}"
        ));
    }
    set_result
        .map(|_| "enabled; readback unavailable".into())
        .map_err(|e| unavailable(label, e))
}

fn resource_limit(resource: libc::__rlimit_resource_t, maximum: u64) -> Result<String, String> {
    let mut inherited = libc::rlimit {
        rlim_cur: 0,
        rlim_max: 0,
    };
    unsafe { checked(libc::getrlimit(resource, &mut inherited) as _) }
        .map_err(|e| unavailable("getrlimit", e))?;
    let limit = libc::rlimit {
        rlim_cur: inherited.rlim_cur.min(maximum),
        rlim_max: inherited.rlim_max.min(maximum),
    };
    // Never raise a tighter limit imposed by Sandstorm or the launcher.
    if limit.rlim_cur == inherited.rlim_cur && limit.rlim_max == inherited.rlim_max {
        return Ok(format!(
            "inherited soft={}, hard={}",
            limit.rlim_cur, limit.rlim_max
        ));
    }
    unsafe { checked(libc::setrlimit(resource, &limit) as _) }
        .map_err(|e| unavailable("setrlimit", e))?;
    Ok(format!("soft={}, hard={}", limit.rlim_cur, limit.rlim_max))
}

fn filesystem_mask(abi: i64) -> u64 {
    (1 << if abi >= 9 {
        17
    } else if abi >= 5 {
        16
    } else if abi >= 3 {
        15
    } else if abi >= 2 {
        14
    } else {
        13
    }) - 1
}

fn create_ruleset(attr: &Ruleset) -> io::Result<OwnedFd> {
    let size = if attr.scoped != 0 {
        24usize
    } else if attr.net != 0 {
        16
    } else {
        8
    };
    unsafe {
        Ok(OwnedFd::from_raw_fd(checked(libc::syscall(
            libc::SYS_landlock_create_ruleset,
            attr,
            size,
            0u32,
        ))? as _))
    }
}

fn install_filesystem(
    abi: i64,
    input: &Path,
    fonts: &Path,
    config: &Path,
    work: &Path,
) -> Result<String, String> {
    let mask = filesystem_mask(abi);
    let ruleset = create_ruleset(&Ruleset {
        fs: mask,
        net: 0,
        scoped: 0,
    })
    .map_err(|e| unavailable("Landlock filesystem ruleset creation", e))?;
    for (path, access) in [
        (input, READ_FILE),
        (fonts, READ_FILE | READ_DIR),
        (config, READ_FILE),
        (work, WORK & mask),
    ] {
        allow(&ruleset, path, access)
            .map_err(|e| unavailable("Landlock filesystem rule addition", e))?;
    }
    restrict(&ruleset)?;
    Ok(format!("active (Landlock ABI {abi})"))
}

fn restrict(ruleset: &OwnedFd) -> Result<(), String> {
    unsafe {
        checked(libc::syscall(
            libc::SYS_landlock_restrict_self,
            ruleset.as_raw_fd(),
            0u32,
        ))
    }
    .map(|_| ())
    .map_err(|e| unavailable("Landlock restrict_self", e))
}

fn optional_landlock(
    abi: Option<i64>,
    minimum: i64,
    net: u64,
    scoped: u64,
) -> Result<String, String> {
    if abi.is_none_or(|abi| abi < minimum) {
        return Err(format!("requires usable Landlock ABI {minimum} or newer"));
    }
    // Separate layers let filesystem, TCP, UDP and scoping remain independent
    // when a host supports only some of them or an outer policy rejects a flag.
    let ruleset = create_ruleset(&Ruleset { fs: 0, net, scoped })
        .map_err(|e| unavailable("Landlock optional ruleset creation", e))?;
    restrict(&ruleset)?;
    Ok("active".into())
}

/// Apply each available protection before parsing or starting threads. Missing
/// security features are reported and do not prevent conversion. Invalid caller
/// paths/configuration remain errors. Input must be outside private scratch.
pub fn enter(input: &Path, output: &Path) -> Result<SecurityReport, Box<dyn std::error::Error>> {
    let mut report = SecurityReport {
        landlock_abi: None,
        features: Vec::new(),
    };
    report.record("inherited_fds_closed", close_inherited_fds());
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
    unsafe {
        std::env::set_var("TMPDIR", &work);
        std::env::set_var("XDG_CACHE_HOME", work.join("cache"));
    }
    report.record(
        "process_dumping_disabled",
        process_flag(
            libc::PR_SET_DUMPABLE,
            libc::PR_GET_DUMPABLE,
            0,
            "PR_SET_DUMPABLE",
        ),
    );
    report.record(
        "no_new_privileges",
        process_flag(
            libc::PR_SET_NO_NEW_PRIVS,
            libc::PR_GET_NO_NEW_PRIVS,
            1,
            "PR_SET_NO_NEW_PRIVS",
        ),
    );
    for (name, resource, maximum) in [
        (
            "address_space_limit",
            libc::RLIMIT_AS,
            4_u64 * 1024 * 1024 * 1024,
        ),
        (
            "output_file_size_limit",
            libc::RLIMIT_FSIZE,
            crate::MAX_PDF_BYTES as u64,
        ),
        ("core_file_size_limit", libc::RLIMIT_CORE, 0),
    ] {
        report.record(name, resource_limit(resource, maximum));
    }
    let abi = unsafe {
        checked(libc::syscall(
            libc::SYS_landlock_create_ruleset,
            std::ptr::null::<Ruleset>(),
            0usize,
            1u32,
        ))
    };
    let fs_result = match abi {
        Ok(abi) if abi >= 1 => {
            report.landlock_abi = Some(abi);
            install_filesystem(abi, &input, &fonts, &config, &work)
        }
        Ok(_) => Err("Landlock reported no supported ABI".into()),
        Err(e) => Err(unavailable("Landlock ABI query", e)),
    };
    let fs_active = fs_result.is_ok();
    match &fs_result {
        Ok(_) => eprintln!(
            "Using Landlock ABI {} for preview",
            report
                .landlock_abi
                .expect("active filesystem isolation has an ABI")
        ),
        Err(reason) => {
            eprintln!("Landlock filesystem isolation unavailable; continuing preview: {reason}")
        }
    }
    report.record("filesystem_isolation", fs_result);
    let abi = report.landlock_abi;
    for (name, minimum) in [
        ("file_truncation_isolation", 3),
        ("device_ioctl_isolation", 5),
        ("pathname_unix_socket_isolation", 9),
    ] {
        report.record(
            name,
            if fs_active && abi.is_some_and(|v| v >= minimum) {
                Ok("active".into())
            } else {
                Err(format!(
                    "requires active filesystem isolation with Landlock ABI {minimum} or newer"
                ))
            },
        );
    }
    for (name, minimum, net, scoped) in [
        ("tcp_isolation", 4, 3, 0),
        ("udp_isolation", 10, 12, 0),
        ("abstract_unix_socket_isolation", 6, 0, 1),
        ("signal_isolation", 6, 0, 2),
    ] {
        report.record(name, optional_landlock(abi, minimum, net, scoped));
    }
    Ok(report)
}
