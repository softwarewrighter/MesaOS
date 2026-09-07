#![no_std]
#![no_main]

use core::panic::PanicInfo;
use mesaos_user::{clock, io, process};

const WIDTH: usize = 25;
const HEIGHT: usize = 13;
const CX: i32 = 12;
const CY: i32 = 6;

// Twelve points around a terminal-cell ellipse, starting at 12 o'clock.
const POINTS: [(i32, i32); 12] = [
    (0, -5),
    (5, -4),
    (10, -2),
    (11, 0),
    (10, 2),
    (5, 4),
    (0, 5),
    (-5, 4),
    (-10, 2),
    (-11, 0),
    (-10, -2),
    (-5, -4),
];

#[unsafe(no_mangle)]
pub extern "C" fn _start() -> ! {
    io::banner("xclock", env!("CARGO_PKG_VERSION"));
    io::print("ASCII analog clock (uptime; Ring-3 has no RTC syscall yet)\n\n");

    let seconds = clock::uptime_seconds() % 86_400;
    let hour = (seconds / 3_600) as usize;
    let minute = ((seconds / 60) % 60) as usize;
    let second = (seconds % 60) as usize;

    let mut canvas = [[b' '; WIDTH]; HEIGHT];
    for (index, (x, y)) in POINTS.iter().enumerate() {
        plot(
            &mut canvas,
            CX + x,
            CY + y,
            if index % 3 == 0 { b'O' } else { b'o' },
        );
    }
    draw_hand(&mut canvas, hour % 12, 2, b'H');
    draw_hand(&mut canvas, minute / 5, 1, b'M');
    draw_hand(&mut canvas, second / 5, 0, b'.');
    plot(&mut canvas, CX, CY, b'@');

    for row in &canvas {
        let _ = io::write_all(io::STDOUT, row);
        io::print("\n");
    }
    io::print("\nH=hour  M=minute  .=second\n");
    process::exit(0)
}

fn draw_hand(canvas: &mut [[u8; WIDTH]; HEIGHT], tick: usize, shorten: i32, mark: u8) {
    let (dx, dy) = POINTS[tick % 12];
    let divisor = 5;
    let end_x = CX + dx * (divisor - shorten) / divisor;
    let end_y = CY + dy * (divisor - shorten) / divisor;
    draw_line(canvas, CX, CY, end_x, end_y, mark);
}

fn draw_line(
    canvas: &mut [[u8; WIDTH]; HEIGHT],
    mut x0: i32,
    mut y0: i32,
    x1: i32,
    y1: i32,
    mark: u8,
) {
    let dx = (x1 - x0).abs();
    let sx = if x0 < x1 { 1 } else { -1 };
    let dy = -(y1 - y0).abs();
    let sy = if y0 < y1 { 1 } else { -1 };
    let mut error = dx + dy;
    loop {
        plot(canvas, x0, y0, mark);
        if x0 == x1 && y0 == y1 {
            break;
        }
        let twice = error * 2;
        if twice >= dy {
            error += dy;
            x0 += sx;
        }
        if twice <= dx {
            error += dx;
            y0 += sy;
        }
    }
}

fn plot(canvas: &mut [[u8; WIDTH]; HEIGHT], x: i32, y: i32, mark: u8) {
    if x >= 0 && y >= 0 && (x as usize) < WIDTH && (y as usize) < HEIGHT {
        canvas[y as usize][x as usize] = mark;
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo<'_>) -> ! {
    io::error("xclock: Rust panic\n");
    process::exit(101)
}
