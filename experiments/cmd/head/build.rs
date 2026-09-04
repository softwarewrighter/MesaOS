fn main() {
    let manifest = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set");
    println!("cargo:rustc-link-arg=-T{manifest}/linker.ld");
    // MesaOS loads ET_EXEC directly and does not apply dynamic relocations.
    println!("cargo:rustc-link-arg=--no-pie");
    println!("cargo:rerun-if-changed=linker.ld");
}
