//! Test-only diagnostic for separating legacy normalization from PDF rendering.
//! Uses the same sandbox and normalization code as the production executable.
use std::path::Path;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        return Err("usage: corpus-normalize INPUT SCRATCH_DIRECTORY".into());
    }
    let source = Path::new(&args[1]);
    let scratch = Path::new(&args[2]);
    let output = scratch.join("preview.pdf");
    davros_preview::sandbox::enter(source, &output)?;
    let prepared = davros_preview::legacy::prepare(source, &output)?;
    let extension = prepared.path().extension().ok_or("Missing extension")?;
    let mut normalized = scratch.join("normalized");
    normalized.set_extension(extension);
    std::fs::copy(prepared.path(), normalized)?;
    Ok(())
}
