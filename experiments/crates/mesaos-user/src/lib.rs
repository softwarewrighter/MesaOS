#![no_std]

//! Minimal Ring-3 support library for freestanding MesaOS programs.

use core::arch::asm;

pub mod errno {
    pub const INVALID: isize = -22;
    pub const TOO_LONG: isize = -36;
}

mod syscall {
    use super::asm;
    pub const READ: usize = 0;
    pub const WRITE: usize = 1;
    pub const OPEN: usize = 2;
    pub const CLOSE: usize = 3;
    pub const EXIT: usize = 60;

    #[inline(always)]
    pub unsafe fn call1(number: usize, arg1: usize) -> isize {
        let result: isize;
        unsafe {
            asm!("syscall", inlateout("rax") number as isize => result, inlateout("rdi") arg1 => _, lateout("rcx") _, lateout("r8") _, lateout("r9") _, lateout("r10") _, lateout("r11") _, options(nostack));
        }
        result
    }

    #[inline(always)]
    pub unsafe fn call3(number: usize, arg1: usize, arg2: usize, arg3: usize) -> isize {
        let result: isize;
        unsafe {
            asm!("syscall", inlateout("rax") number as isize => result, inlateout("rdi") arg1 => _, inlateout("rsi") arg2 => _, inlateout("rdx") arg3 => _, lateout("rcx") _, lateout("r8") _, lateout("r9") _, lateout("r10") _, lateout("r11") _, options(nostack));
        }
        result
    }
}

pub mod io {
    use super::syscall;
    pub const STDOUT: usize = 1;
    pub const STDERR: usize = 2;

    pub fn write_all(fd: usize, mut bytes: &[u8]) -> Result<(), isize> {
        while !bytes.is_empty() {
            let result =
                unsafe { syscall::call3(syscall::WRITE, fd, bytes.as_ptr() as usize, bytes.len()) };
            if result <= 0 {
                return Err(result);
            }
            bytes = &bytes[result as usize..];
        }
        Ok(())
    }

    pub fn print(text: &str) {
        let _ = write_all(STDOUT, text.as_bytes());
    }
    pub fn error(text: &str) {
        let _ = write_all(STDERR, text.as_bytes());
    }
    pub fn banner(name: &str, version: &str) {
        print("MesaOS experiment: ");
        print(name);
        print(" v");
        print(version);
        print(" (Ring 3, no_std Rust)\n");
    }
}

pub mod fs {
    use super::syscall;
    pub struct File {
        fd: usize,
    }

    impl File {
        /// `path` must be NUL terminated.
        pub fn open(path: &[u8]) -> Result<Self, isize> {
            if path.last() != Some(&0) {
                return Err(super::errno::INVALID);
            }
            let result = unsafe { syscall::call3(syscall::OPEN, path.as_ptr() as usize, 0, 0) };
            if result < 0 {
                Err(result)
            } else {
                Ok(Self {
                    fd: result as usize,
                })
            }
        }

        pub fn read(&mut self, buffer: &mut [u8]) -> Result<usize, isize> {
            let result = unsafe {
                syscall::call3(
                    syscall::READ,
                    self.fd,
                    buffer.as_mut_ptr() as usize,
                    buffer.len(),
                )
            };
            if result < 0 {
                Err(result)
            } else {
                Ok(result as usize)
            }
        }
    }

    impl Drop for File {
        fn drop(&mut self) {
            unsafe {
                syscall::call1(syscall::CLOSE, self.fd);
            }
        }
    }
}

pub mod args {
    use super::{errno, fs::File};

    /// A fixed-capacity, NUL-terminated argument read from a request file.
    pub struct Argument<const N: usize> {
        bytes: [u8; N],
        len: usize,
    }

    impl<const N: usize> Argument<N> {
        pub fn from_file(request_path: &[u8]) -> Result<Self, isize> {
            let mut result = Self {
                bytes: [0; N],
                len: 0,
            };
            let mut file = File::open(request_path)?;
            let count = file.read(&mut result.bytes)?;
            // MesaOS currently returns from close(2) with more register
            // clobbering than the standard ABI permits. Keep this short-lived
            // request descriptor open; process teardown releases it.
            core::mem::forget(file);
            let trimmed = result.bytes[..count]
                .iter()
                .position(|byte| *byte == b'\n' || *byte == b'\r' || *byte == 0)
                .unwrap_or(count);
            if trimmed == 0 {
                return Err(errno::INVALID);
            }
            if trimmed >= N {
                return Err(errno::TOO_LONG);
            }
            result.len = trimmed;
            result.bytes[trimmed] = 0;
            Ok(result)
        }

        pub fn as_c_path(&self) -> &[u8] {
            &self.bytes[..=self.len]
        }

        pub fn as_bytes(&self) -> &[u8] {
            &self.bytes[..self.len]
        }

        /// Parse a decimal count, accepting either `5` or the `head` form `-5`.
        pub fn parse_line_count(&self) -> Result<usize, isize> {
            let mut value = 0_usize;
            let mut saw_digit = false;
            for byte in &self.bytes[..self.len] {
                // Be tolerant of the shell bridge's option marker and spacing.
                if *byte == b'-' || *byte == b' ' || *byte == b'\t' {
                    continue;
                }
                if *byte < b'0' || *byte > b'9' {
                    return Err(errno::INVALID);
                }
                saw_digit = true;
                value = value
                    .checked_mul(10)
                    .and_then(|n| n.checked_add((byte - b'0') as usize))
                    .ok_or(errno::INVALID)?;
            }
            if saw_digit {
                Ok(value)
            } else {
                Err(errno::INVALID)
            }
        }
    }

    #[cfg(test)]
    mod tests {
        use super::Argument;

        #[test]
        fn parses_head_style_line_count() {
            let mut argument = Argument::<32> {
                bytes: [0; 32],
                len: 2,
            };
            argument.bytes[..2].copy_from_slice(b"-5");
            assert_eq!(argument.parse_line_count(), Ok(5));
        }
    }
}

pub mod process {
    use super::syscall;
    pub fn exit(status: usize) -> ! {
        unsafe {
            syscall::call1(syscall::EXIT, status);
        }
        loop {
            core::hint::spin_loop();
        }
    }
}
