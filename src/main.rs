use std::{io::Read, path::Path};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    let check = args.get(1).is_some_and(|arg| arg == "--check-sandbox");
    if args.len() != if check { 4 } else { 3 } {
        return Err(
            "usage: davros-preview [--check-sandbox] INPUT OUTPUT.pdf (DOC, DOCX, XLS, XLSX, PPT, PPTX, ODT, ODS, ODP)".into(),
        );
    }
    let input = Path::new(&args[1 + usize::from(check)]);
    let output = Path::new(&args[2 + usize::from(check)]);
    let security = davros_preview::sandbox::enter(input, output)?;
    if check {
        let features: serde_json::Map<String, serde_json::Value> = security
            .features
            .iter()
            .map(|(name, enabled, detail)| {
                (
                    (*name).into(),
                    serde_json::json!({"enabled": enabled, "detail": detail}),
                )
            })
            .collect();
        println!(
            "{}",
            serde_json::to_string_pretty(&serde_json::json!({
                "schema_version": 1,
                "policy": "best_effort",
                "landlock_abi": security.landlock_abi,
                "degraded": security.features.iter().any(|(_, enabled, _)| !enabled),
                "features": features,
            }))?
        );
        return Ok(());
    }
    let input = davros_preview::legacy::prepare(input, output)?;
    let pdf = match input
        .path()
        .extension()
        .and_then(|s| s.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("docx") => docxide_pdf::render_docx_to_pdf(input.path())?,
        Some("xlsx" | "pptx") => {
            let options = office2pdf::config::ConvertOptions {
                last_resort_font_family: Some("Liberation Sans".into()),
                ..Default::default()
            };
            let result = office2pdf::convert_with_options(input.path(), &options)?;
            result.pdf
        }
        Some(extension @ ("odt" | "ods" | "odp")) => {
            let mut bytes = Vec::new();
            std::fs::File::open(input.path())?
                .take(32 * 1024 * 1024 + 1)
                .read_to_end(&mut bytes)?;
            if bytes.len() > 32 * 1024 * 1024 {
                return Err("Document exceeds 32 MiB".into());
            }
            match extension {
                "odt" => lo_writer::try_to_pdf(&lo_writer::from_odt_bytes("", &bytes)?)?,
                "ods" => lo_calc::to_pdf(&lo_calc::from_ods_bytes("", &bytes)?),
                "odp" => lo_impress::to_pdf(&lo_impress::from_odp_bytes("", &bytes)?),
                _ => unreachable!(),
            }
        }
        _ => return Err("Unsupported normalized document format".into()),
    };
    davros_preview::write_pdf(output, &pdf)?;
    Ok(())
}
