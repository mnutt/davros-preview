#[cfg(target_os = "linux")]
pub mod sandbox;
#[cfg(not(target_os = "linux"))]
compile_error!("Native document previews require Linux");

pub mod legacy;

use std::{fs::File, io::Read, path::Path};

/// Maximum PDF output size, shared with the renderer process file limit.
pub const MAX_PDF_BYTES: usize = 256 * 1024 * 1024;

/// Bound input size before parsing. Process hardening is applied by sandbox::enter.
fn bounded_input(input: &Path) -> Result<File, Box<dyn std::error::Error>> {
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

/// Publish only a complete, bounded PDF; never follow or overwrite an existing
/// output symlink/hardlink. The caller owns the private scratch directory.
pub fn write_pdf(output: &Path, bytes: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    use std::io::Write;
    if bytes.len() > MAX_PDF_BYTES {
        return Err("PDF exceeds 256 MiB".into());
    }
    if !bytes.starts_with(b"%PDF-") {
        return Err("Converter did not produce a PDF".into());
    }
    let mut staged =
        tempfile::NamedTempFile::new_in(output.parent().ok_or("Missing output directory")?)?;
    staged.write_all(bytes)?;
    staged.persist_noclobber(output)?;
    Ok(())
}

#[cfg(test)]
mod security_tests {
    use super::*;
    #[test]
    fn output_is_bounded_and_does_not_overwrite_links() {
        let work = tempfile::tempdir().unwrap();
        let secret = work.path().join("secret");
        let output = work.path().join("preview.pdf");
        std::fs::write(&secret, b"secret").unwrap();
        std::os::unix::fs::symlink(&secret, &output).unwrap();
        assert!(write_pdf(&output, b"%PDF-test").is_err());
        assert_eq!(std::fs::read(&secret).unwrap(), b"secret");
        std::fs::remove_file(&output).unwrap();
        std::fs::hard_link(&secret, &output).unwrap();
        assert!(write_pdf(&output, b"%PDF-test").is_err());
        assert_eq!(std::fs::read(&secret).unwrap(), b"secret");
        std::fs::remove_file(&output).unwrap();
        assert!(write_pdf(&output, b"invalid").is_err());
        assert_eq!(
            write_pdf(&output, &vec![0; MAX_PDF_BYTES + 1])
                .unwrap_err()
                .to_string(),
            "PDF exceeds 256 MiB"
        );
        assert!(!output.exists());
        write_pdf(&output, b"%PDF-test").unwrap();
        assert_eq!(std::fs::read(&output).unwrap(), b"%PDF-test");
    }
}
