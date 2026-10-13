#[cfg(target_os = "linux")]
pub mod sandbox;
#[cfg(not(target_os = "linux"))]
compile_error!("Native document previews require Linux Landlock");

pub mod legacy;

use std::{fs::File, io::Read, path::Path};

/// Set process limits and bound input size before any document parsing.
fn bounded_input(input: &Path) -> Result<File, Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    unsafe {
        for (resource, bytes) in [
            (libc::RLIMIT_AS, 4_u64 * 1024 * 1024 * 1024),
            (libc::RLIMIT_FSIZE, 128_u64 * 1024 * 1024),
            (libc::RLIMIT_CORE, 0),
        ] {
            let limit = libc::rlimit {
                rlim_cur: bytes,
                rlim_max: bytes,
            };
            if libc::setrlimit(resource, &limit) != 0 {
                return Err(std::io::Error::last_os_error().into());
            }
        }
    }
    let file = File::open(input)?;
    if file.metadata()?.len() > 32 * 1024 * 1024 {
        return Err("Document exceeds 32 MiB".into());
    }
    Ok(file)
}

/// Bound advertised and actual decompression before handing a ZIP to a converter.
pub fn validate(input: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let mut archive = zip::ZipArchive::new(bounded_input(input)?)?;
    if archive.len() > 10_000 {
        return Err("Too many archive entries".into());
    }
    let mut total = 0;
    for index in 0..archive.len() {
        let entry = archive.by_index(index)?;
        if entry.size() > 32 * 1024 * 1024 {
            return Err("Archive entry exceeds 32 MiB".into());
        }
        let bytes = std::io::copy(&mut entry.take(32 * 1024 * 1024 + 1), &mut std::io::sink())?;
        total += bytes;
        if bytes > 32 * 1024 * 1024 || total > 128 * 1024 * 1024 {
            return Err("Decompressed document exceeds preview limit".into());
        }
    }
    Ok(())
}
