use anyhow::Result;
use libbpf_rs::skel::{OpenSkel, SkelBuilder};
use libbpf_rs::{MapCore, MapFlags};
use std::mem::MaybeUninit;

// -----------------------------------------------------------------------------
// BPF SKELETON INCLUSION
// -----------------------------------------------------------------------------
#[allow(non_camel_case_types)]
#[allow(non_snake_case)]
#[allow(dead_code)]
#[allow(non_upper_case_globals)]
pub mod sentry_dictator_skel {
    include!(concat!(env!("OUT_DIR"), "/sentry_dictator_skel.rs"));
}

use sentry_dictator_skel::*;

// -----------------------------------------------------------------------------
// USER-SPACE TO KERNEL CONTROLLER
// -----------------------------------------------------------------------------
pub struct BpfController<'a> {
    _link: libbpf_rs::Link,
    _skel: SentryDictatorSkel<'a>,
}

impl<'a> BpfController<'a> {
    /// Instantly updates the VIP Process ID inside the kernel map (O(1) complexity).
    pub fn update_vip_pid(&mut self, pid: u32) -> Result<()> {
        let key = 0u32.to_ne_bytes();
        let value = pid.to_ne_bytes();
        self._skel.maps.vip_pid_map.update(&key, &value, MapFlags::ANY)?;
        Ok(())
    }
}

// -----------------------------------------------------------------------------
// ENGINE ENTRYPOINT
// -----------------------------------------------------------------------------
/// Compiles, loads, and attaches the Ring -1 Dictator scheduler into the Linux kernel via sched_ext.
pub fn launch_bpf_engine() -> Result<BpfController<'static>> {
    println!("[BPF-ENGINE] Opening SENTRY Ring -1 Dictator skeleton...");
    
    let skel_builder = SentryDictatorSkelBuilder::default();
    let mut open_obj = MaybeUninit::uninit();
    let open_skel = skel_builder.open(&mut open_obj)?;
    
    println!("[BPF-ENGINE] Loading BPF program into kernel verifier...");
    // Must be declared mutable so we can attach struct_ops maps
    let mut skel = open_skel.load()?;
    
    println!("[BPF-ENGINE] Attaching sched_ext struct_ops dictator scheduler...");
    let link = skel.maps.sentry_ops.attach_struct_ops()?;

    println!("[BPF-ENGINE] SUCCESS: SENTRY Ring -1 Dictator is active in the kernel!");

    let static_skel: SentryDictatorSkel<'static> = unsafe {
        std::mem::transmute(skel)
    };

    Ok(BpfController {
        _link: link,
        _skel: static_skel,
    })
}
