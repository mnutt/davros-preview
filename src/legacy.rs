//! Normalize legacy Office files inside the caller's preview sandbox.
use office_oxide::{Document, format::DocumentFormat};
use std::{
    error::Error,
    path::{Path, PathBuf},
};

pub struct PreparedInput {
    path: PathBuf,
    // Keep the intermediate alive through rendering; remove it on success/error.
    _intermediate: Option<tempfile::NamedTempFile>,
}

impl PreparedInput {
    pub fn path(&self) -> &Path {
        &self.path
    }
}

/// Must be called after sandbox::enter, before any converter parses the input.
pub fn prepare(input: &Path, output: &Path) -> Result<PreparedInput, Box<dyn Error>> {
    let extension = input
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if !matches!(
        extension.as_str(),
        "doc" | "docx" | "xls" | "xlsx" | "ppt" | "pptx" | "odt" | "ods" | "odp"
    ) {
        return Err(
            "Supported input formats: doc, docx, xls, xlsx, ppt, pptx, odt, ods, odp".into(),
        );
    }
    let formats = match extension.as_str() {
        "doc" => Some((DocumentFormat::Doc, DocumentFormat::Docx)),
        "xls" => Some((DocumentFormat::Xls, DocumentFormat::Xlsx)),
        "ppt" => Some((DocumentFormat::Ppt, DocumentFormat::Pptx)),
        _ => None,
    };
    if let Some((source, target)) = formats {
        // Use the explicit binary reader: ZIPs renamed to .doc/.xls/.ppt must
        // not bypass our decompression validation via automatic format sniffing.
        let document = Document::from_reader(crate::bounded_input(input)?, source)?;
        if document.format() != source {
            return Err("Legacy document content does not match its extension".into());
        }
        let mut intermediate = tempfile::Builder::new()
            .prefix("davros-legacy-")
            .suffix(&format!(".{}", target.extension()))
            .tempfile_in(
                output
                    .parent()
                    .ok_or("Output requires a parent directory")?,
            )?;
        office_oxide::create::create_from_ir_to_writer(
            &document.to_ir(),
            target,
            intermediate.as_file_mut(),
        )?;
        crate::validate(intermediate.path())?;
        Ok(PreparedInput {
            path: intermediate.path().to_owned(),
            _intermediate: Some(intermediate),
        })
    } else {
        crate::validate(input)?;
        Ok(PreparedInput {
            path: input.to_owned(),
            _intermediate: None,
        })
    }
}
