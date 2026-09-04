#![no_std]
#![no_main]

use core::panic::PanicInfo;
use mesaos_user::{args::Argument, fs::File, io, process};

const PATH_REQUEST: &[u8] = b"/tmp/head.path\0";
const LINES_REQUEST: &[u8] = b"/tmp/head.lines\0";
const DEFAULT_LINES: usize = 10;

#[unsafe(no_mangle)]
pub extern "C" fn _start() -> ! {
    io::banner("head", env!("CARGO_PKG_VERSION"));

    let path = match Argument::<256>::from_file(PATH_REQUEST) {
        Ok(path) => path,
        Err(_) => {
            io::error("head: missing or invalid /tmp/head.path\n");
            process::exit(2);
        }
    };
    let line_limit = match Argument::<32>::from_file(LINES_REQUEST) {
        Ok(value) => match value.parse_line_count() {
            Ok(count) => count,
            Err(_) => {
                io::error("head: invalid count; using 10\n");
                DEFAULT_LINES
            }
        },
        Err(_) => {
            io::error("head: missing count; using 10\n");
            DEFAULT_LINES
        }
    };

    let mut file = match File::open(path.as_c_path()) {
        Ok(file) => file,
        Err(_) => {
            io::error("head: cannot open requested input file\n");
            process::exit(1);
        }
    };

    let mut buffer = [0_u8; 512];
    let mut lines = 0;
    'input: loop {
        let count = match file.read(&mut buffer) {
            Ok(count) => count,
            Err(_) => {
                io::error("head: read failed\n");
                process::exit(1);
            }
        };
        if count == 0 || line_limit == 0 {
            break;
        }

        let bytes = &buffer[..count];
        for (index, byte) in bytes.iter().enumerate() {
            if *byte == b'\n' {
                lines += 1;
                if lines == line_limit {
                    let _ = io::write_all(io::STDOUT, &bytes[..=index]);
                    break 'input;
                }
            }
        }
        let _ = io::write_all(io::STDOUT, bytes);
    }
    process::exit(0)
}

#[panic_handler]
fn panic(_info: &PanicInfo<'_>) -> ! {
    io::error("head: Rust panic\n");
    process::exit(101)
}
