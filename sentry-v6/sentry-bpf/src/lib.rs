use anyhow::Result;
use libbpf_rs::skel::{OpenSkel, SkelBuilder};
use libbpf_rs::{MapCore, MapFlags}; // THE CRITICAL MISSING IMPORT
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
    skel: SentryDictatorSkel<'a>,
}

impl<'a> BpfController<'a> {
    /// Converts a HashSet of process IDs into a continuous flat array and pushes it to eBPF.
    pub fn sync_vip_tree(&mut self, vip_tree: &HashSet<u32>) -> Result<()> {
        // 1. Clear the old tree to prevent ghost VIPs
        let mut keys_to_delete = Vec::new();
        for key in self.skel.maps.vip_process_tree.keys() {
            keys_to_delete.push(key);
        }
        for key in keys_to_delete {
            let _ = self.skel.maps.vip_process_tree.delete(&key);
        }

        // 2. Blast the new tree into Ring -1
        let value = 1u8;
        for &pid in vip_tree {
            self.skel.maps.vip_process_tree.update(&pid.to_ne_bytes(), &value.to_ne_bytes(), MapFlags::ANY)?;
        }
        Ok(())
    }

    /// Hard-pins the VIP arrays and Background arrays into the eBPF hardware router.
    pub fn sync_core_topology(&mut self, vip_cores: &[u32], bg_cores: &[u32]) -> Result<()> {
        // Sync VIP (P-Cores)
        self.skel.maps.vip_cores_count.update(&0u32.to_ne_bytes(), &(vip_cores.len() as u32).to_ne_bytes(), MapFlags::ANY)?;
        for (i, &core_id) in vip_cores.iter().enumerate() {
            self.skel.maps.vip_cores_list.update(&(i as u32).to_ne_bytes(), &core_id.to_ne_bytes(), MapFlags::ANY)?;
        }

        // Sync Quarantine (E-Cores or partitioned cores)
        self.skel.maps.bg_cores_count.update(&0u32.to_ne_bytes(), &(bg_cores.len() as u32).to_ne_bytes(), MapFlags::ANY)?;
        for (i, &core_id) in bg_cores.iter().enumerate() {
            self.skel.maps.bg_cores_list.update(&(i as u32).to_ne_bytes(), &core_id.to_ne_bytes(), MapFlags::ANY)?;
        }

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
        skel: static_skel,
    })
}
