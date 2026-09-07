fn main() {
    let manifest = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set");
    println!("cargo:rustc-link-arg=-T{manifest}/linker.ld");
    println!("cargo:rustc-link-arg=--no-pie");
    println!("cargo:rerun-if-changed=linker.ld");
}
