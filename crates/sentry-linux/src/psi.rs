use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PsiAverage {
    /// Percentage of elapsed time stalled during the corresponding window.
    pub avg10: f64,
    pub avg60: f64,
    pub avg300: f64,
    /// Cumulative stall time in microseconds.
    pub total: u64,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PsiSnapshot {
    pub some: PsiAverage,
    /// `full` is not present for every resource/kernel combination (notably CPU).
    pub full: Option<PsiAverage>,
}

pub fn read_snapshot(resource: &str) -> Result<PsiSnapshot, String> {
    if !matches!(resource, "cpu" | "memory" | "io") {
        return Err(format!("unsupported PSI resource `{resource}`"));
    }
    read_snapshot_from(Path::new("/proc/pressure"), resource)
}

/// Read a PSI snapshot from an injectable root. Used by deterministic tests.
pub fn read_snapshot_from(root: &Path, resource: &str) -> Result<PsiSnapshot, String> {
    if !matches!(resource, "cpu" | "memory" | "io") {
        return Err(format!("unsupported PSI resource `{resource}`"));
    }
    let path: PathBuf = root.join(resource);
    let contents = fs::read_to_string(&path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    parse_snapshot(&contents)
}

pub fn parse_snapshot(contents: &str) -> Result<PsiSnapshot, String> {
    let mut some = None;
    let mut full = None;

    for line in contents.lines().filter(|line| !line.trim().is_empty()) {
        let mut fields = line.split_whitespace();
        let kind = fields.next().ok_or_else(|| "empty PSI record".to_owned())?;
        let average = parse_average(fields)?;

        match kind {
            "some" if some.is_none() => some = Some(average),
            "full" if full.is_none() => full = Some(average),
            "some" | "full" => return Err(format!("duplicate PSI record `{kind}`")),
            other => return Err(format!("unrecognised PSI record `{other}`")),
        }
    }

    let some = some.ok_or_else(|| "PSI file did not contain a `some` record".to_owned())?;
    Ok(PsiSnapshot { some, full })
}

fn parse_average<'a>(fields: impl Iterator<Item = &'a str>) -> Result<PsiAverage, String> {
    let mut avg10 = None;
    let mut avg60 = None;
    let mut avg300 = None;
    let mut total = None;

    for field in fields {
        let Some((key, value)) = field.split_once('=') else {
            return Err(format!("malformed PSI field `{field}`"));
        };
        match key {
            "avg10" => avg10 = Some(parse_percentage(key, value)?),
            "avg60" => avg60 = Some(parse_percentage(key, value)?),
            "avg300" => avg300 = Some(parse_percentage(key, value)?),
            "total" => {
                total = Some(
                    value
                        .parse::<u64>()
                        .map_err(|_| format!("invalid PSI field `{key}={value}`"))?,
                )
            }
            // Ignore future kernel fields while requiring the documented fields.
            _ => {}
        }
    }

    Ok(PsiAverage {
        avg10: avg10.ok_or_else(|| "PSI record is missing avg10".to_owned())?,
        avg60: avg60.ok_or_else(|| "PSI record is missing avg60".to_owned())?,
        avg300: avg300.ok_or_else(|| "PSI record is missing avg300".to_owned())?,
        total: total.ok_or_else(|| "PSI record is missing total".to_owned())?,
    })
}

fn parse_percentage(key: &str, value: &str) -> Result<f64, String> {
    let parsed = value
        .parse::<f64>()
        .map_err(|_| format!("invalid PSI field `{key}={value}`"))?;
    if !parsed.is_finite() || !(0.0..=100.0).contains(&parsed) {
        return Err(format!("PSI percentage `{key}={value}` is out of range"));
    }
    Ok(parsed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_some_and_full_records() {
        let input = concat!(
            "some avg10=1.25 avg60=0.50 avg300=0.10 total=1234\n",
            "full avg10=0.25 avg60=0.10 avg300=0.01 total=200\n",
        );
        let parsed = parse_snapshot(input).unwrap();
        assert_eq!(parsed.some.avg10, 1.25);
        assert_eq!(parsed.full.unwrap().total, 200);
    }

    #[test]
    fn accepts_some_only_snapshot() {
        let parsed = parse_snapshot("some avg10=0 avg60=0 avg300=0 total=0\n").unwrap();
        assert!(parsed.full.is_none());
    }

    #[test]
    fn accepts_unknown_future_fields() {
        let parsed =
            parse_snapshot("some avg10=0 avg60=0 avg300=0 total=0 future_field=7\n").unwrap();
        assert_eq!(parsed.some.total, 0);
    }

    #[test]
    fn rejects_duplicate_records() {
        let input = concat!(
            "some avg10=0 avg60=0 avg300=0 total=0\n",
            "some avg10=0 avg60=0 avg300=0 total=0\n",
        );
        assert!(parse_snapshot(input).is_err());
    }

    #[test]
    fn rejects_out_of_range_average() {
        assert!(parse_snapshot("some avg10=101 avg60=0 avg300=0 total=0\n").is_err());
    }
}
