//! Test-only executable; not included in the runtime package.
use std::{fs, io, net::TcpStream, os::unix::net::UnixStream, path::Path, process::Command};
#[track_caller]
fn denied<T>(result: io::Result<T>) {
    let error = result
        .err()
        .expect("forbidden operation unexpectedly succeeded");
    assert!(
        matches!(
            error.raw_os_error(),
            Some(libc::EACCES | libc::EPERM | libc::EROFS)
        ),
        "unexpected denial: {error}"
    );
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    let input = Path::new(&args[1]);
    let output = Path::new(&args[2]);
    let root = input.parent().unwrap();
    let abi = unsafe { libc::syscall(libc::SYS_landlock_create_ruleset, 0usize, 0usize, 1u32) };
    davros_preview::sandbox::enter(input, output)?;
    assert_eq!(fs::read(input)?, b"input");
    assert!(!fs::read(std::env::var_os("FONTCONFIG_FILE").unwrap())?.is_empty());
    assert!(
        fs::read_dir(std::env::var_os("DAVROS_PREVIEW_FONTS").unwrap())?
            .next()
            .is_some()
    );
    fs::write(output, b"output")?;
    assert_eq!(fs::read(output)?, b"output");
    fs::create_dir(output.parent().unwrap().join("temporary"))?;
    denied(fs::read(root.join("secret")));
    denied(fs::write(root.join("secret"), b"bad"));
    denied(fs::write(input, b"bad"));
    denied(fs::write(root.join("new-file"), b"bad"));
    denied(fs::read_dir(root));
    denied(fs::read(output.parent().unwrap().join("escape")));
    denied(fs::write(
        std::env::var_os("FONTCONFIG_FILE").unwrap(),
        b"bad",
    ));
    denied(fs::write(
        Path::new(&std::env::var_os("DAVROS_PREVIEW_FONTS").unwrap()).join("new-font"),
        b"bad",
    ));
    denied(Command::new(&args[0]).arg("should-not-execute").status());
    // The driver deliberately passes an open secret file, with CLOEXEC cleared.
    assert_eq!(unsafe { libc::fcntl(198, libc::F_GETFD) }, -1);
    assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::EBADF));
    if abi >= 4 {
        denied(TcpStream::connect(&args[3]));
    }
    if abi >= 6 {
        assert_eq!(unsafe { libc::kill(libc::getppid(), 0) }, -1);
        assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::EPERM));
        use std::os::linux::net::SocketAddrExt;
        let addr = std::os::unix::net::SocketAddr::from_abstract_name(args[4].as_bytes())?;
        denied(UnixStream::connect_addr(&addr));
    }
    if abi >= 9 {
        denied(UnixStream::connect(root.join("listener.sock")));
    }
    let secret = root.join("secret");
    std::thread::spawn(move || denied(fs::read(secret)))
        .join()
        .unwrap();
    println!(
        "PASS: filesystem, read-only input/fonts, inherited FDs, exec, thread inheritance, supported sockets/signals (ABI {abi})"
    );
    Ok(())
}
