use anyhow::Result;
use libbpf_rs::skel::{OpenSkel, SkelBuilder};
use libbpf_rs::{MapCore, MapFlags};
use std::collections::HashSet;
use std::mem::MaybeUninit;

#[allow(non_camel_case_types)]
#[allow(non_snake_case)]
#[allow(dead_code)]
#[allow(non_upper_case_globals)]
pub mod sentry_dictator_skel {
    include!(concat!(env!("OUT_DIR"), "/sentry_dictator_skel.rs"));
}
use sentry_dictator_skel::*;

pub struct BpfController<'a> {
    _link: libbpf_rs::Link,
    _skel: SentryDictatorSkel<'a>,
    // Tracks current VIPs so we can selectively delete old ones on focus switch
    active_vip_tree: HashSet<u32>,
}

impl<'a> BpfController<'a> {
    /// Syncs the new process tree into the kernel, cleaning up old PIDs.
    pub fn sync_vip_tree(&mut self, new_tree: &HashSet<u32>) -> Result<()> {
        let val = 1u8.to_ne_bytes();

        // 1. Remove PIDs that are no longer in focus
        for pid in &self.active_vip_tree {
            if !new_tree.contains(pid) {
                let key = pid.to_ne_bytes();
                // Ignore ENOENT (error 2) if the PID died and was already cleaned up naturally
                let _ = self._skel.maps.vip_process_tree.delete(&key);
            }
        }

        // 2. Insert new PIDs
        for pid in new_tree {
            if !self.active_vip_tree.contains(pid) {
                let key = pid.to_ne_bytes();
                self._skel.maps.vip_process_tree.update(&key, &val, MapFlags::ANY)?;
            }
        }

        self.active_vip_tree = new_tree.clone();
        Ok(())
    }
}

pub fn launch_bpf_engine() -> Result<BpfController<'static>> {
    println!("[BPF-ENGINE] Opening SENTRY Ring -1 Dictator skeleton...");
    
    let skel_builder = SentryDictatorSkelBuilder::default();
    let mut open_obj = MaybeUninit::uninit();
    let open_skel = skel_builder.open(&mut open_obj)?;
    
    let mut skel = open_skel.load()?;
    let link = skel.maps.sentry_ops.attach_struct_ops()?;

    let static_skel: SentryDictatorSkel<'static> = unsafe {
        std::mem::transmute(skel)
    };

    Ok(BpfController {
        _link: link,
        _skel: static_skel,
        active_vip_tree: HashSet::new(),
    })
}
