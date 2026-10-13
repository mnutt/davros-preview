use std::path::Path;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        return Err(
            "usage: davros-preview INPUT OUTPUT.pdf (DOC, DOCX, XLS, XLSX, PPT, PPTX)".into(),
        );
    }
    let input = Path::new(&args[1]);
    let output = Path::new(&args[2]);
    davros_preview::sandbox::enter(input, output)?;
    let input = davros_preview::legacy::prepare(input, output)?;
    match input
        .path()
        .extension()
        .and_then(|s| s.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("docx") => docxide_pdf::convert_docx_to_pdf(input.path(), output)?,
        Some("xlsx" | "pptx") => {
            let options = office2pdf::config::ConvertOptions {
                last_resort_font_family: Some("Liberation Sans".into()),
                ..Default::default()
            };
            let result = office2pdf::convert_with_options(input.path(), &options)?;
            std::fs::write(output, result.pdf)?;
        }
        _ => return Err("Unsupported normalized document format".into()),
    }
    Ok(())
}
