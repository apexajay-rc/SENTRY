use scx_utils::BpfBuilder;

fn main() {
    println!("cargo:rerun-if-changed=bpf/main.bpf.c");

    let mut builder = BpfBuilder::new().expect("Failed to initialize BpfBuilder");

    // We explicitly tell it to name the output "sentry_dictator"
    // The builder will output "sentry_dictator_skel.rs" to OUT_DIR.
    builder.enable_skel("bpf/main.bpf.c", "sentry_dictator");

    builder.build().expect("BpfBuilder failed to execute");
}
