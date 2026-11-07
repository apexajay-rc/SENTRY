use std::fs;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CgroupV2Info {
    /// Controllers available to the current cgroup (from `cgroup.controllers`).
    pub available_controllers: Vec<String>,
    /// Controllers enabled for children of the current cgroup.
    pub enabled_for_children: Vec<String>,
}

pub fn inspect_unified_hierarchy() -> Result<CgroupV2Info, String> {
    inspect_at(Path::new("/sys/fs/cgroup"))
}

pub fn inspect_at(root: &Path) -> Result<CgroupV2Info, String> {
    let controllers_path = root.join("cgroup.controllers");
    let subtree_path = root.join("cgroup.subtree_control");
    let available = fs::read_to_string(&controllers_path)
        .map_err(|error| format!("cannot read {}: {error}", controllers_path.display()))?;
    let enabled = fs::read_to_string(&subtree_path)
        .map_err(|error| format!("cannot read {}: {error}", subtree_path.display()))?;

    Ok(CgroupV2Info {
        available_controllers: split_tokens(&available),
        enabled_for_children: split_tokens(&enabled),
    })
}

fn split_tokens(contents: &str) -> Vec<String> {
    contents.split_whitespace().map(str::to_owned).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splits_controller_lists() {
        assert_eq!(
            split_tokens("cpu memory io pids\n"),
            ["cpu", "memory", "io", "pids"]
        );
        assert!(split_tokens("").is_empty());
    }
}
