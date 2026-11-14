//! Lantern compiler library (M0: stub only).

/// A compiler diagnostic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Diag {
    /// The requested stage does not exist yet.
    NotImplemented,
    /// A source error at a 1-based line.
    Error { line: usize, message: String },
}

/// Parse `src` and return the AST in its canonical text form.
pub fn parse_to_ast(_src: &str) -> Result<String, Diag> {
    Err(Diag::NotImplemented)
}
