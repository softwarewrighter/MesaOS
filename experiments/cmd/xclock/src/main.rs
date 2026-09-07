#![no_std]
#![no_main]

use core::panic::PanicInfo;
use mesaos_user::{clock, display, io, process};

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
    let mut previous = u64::MAX;
    loop {
        if process::ctrl_c_pending() {
            display::clear();
            display::set_color(display::TEXT);
            io::print("xclock stopped by Ctrl+C.\n");
            process::exit(0)
        }
        let now = clock::rtc_seconds() % 86_400;
        if now != previous {
            render(now);
            previous = now;
        }
        // The safe launcher uses one CPU, where cooperative scheduling is more
        // reliable than MesaOS's current SMP/preemption path.
        clock::sleep(100);
    }
}

fn render(seconds: u64) {
    let hour = (seconds / 3_600) as usize;
    let minute = ((seconds / 60) % 60) as usize;
    let second = (seconds % 60) as usize;

    let mut canvas = [[b' '; WIDTH]; HEIGHT];
    for (index, (x, y)) in POINTS.iter().enumerate() {
        let mark = match index {
            0 => b'2',
            3 => b'3',
            6 => b'6',
            9 => b'9',
            _ => b'.',
        };
        plot(&mut canvas, CX + x, CY + y, mark);
        if index == 0 {
            plot(&mut canvas, CX + x - 1, CY + y, b'1');
        }
    }
    // Internal markers let the renderer color hand dots independently of rim dots.
    draw_hand(&mut canvas, ((hour % 12) * 5 + minute / 12) % 60, 2, b'h');
    draw_hand(&mut canvas, minute, 1, b'm');
    draw_hand(&mut canvas, second, 0, b's');
    plot(&mut canvas, CX, CY, b'@');

    display::clear();
    io::banner("xclock", env!("CARGO_PKG_VERSION"));
    io::print("MesaOS RTC time (updates once per second)\n\n");
    for row in &canvas {
        write_colored(row);
        io::print("\n");
    }
    io::print("\n");
    display::set_color(display::BLUE);
    io::print("o=hour  *=minute");
    display::set_color(display::TEXT);
    io::print("  ");
    display::set_color(display::RED);
    io::print(".=sweep second");
    display::set_color(display::TEXT);
    io::print("\nTime: ");
    write_time(hour, minute, second);
    io::print("\n");
}

fn draw_hand(canvas: &mut [[u8; WIDTH]; HEIGHT], tick: usize, shorten: i32, mark: u8) {
    let index = (tick / 5) % 12;
    let next = (index + 1) % 12;
    let fraction = (tick % 5) as i32;
    let (x0, y0) = POINTS[index];
    let (x1, y1) = POINTS[next];
    let dx = x0 + (x1 - x0) * fraction / 5;
    let dy = y0 + (y1 - y0) * fraction / 5;
    let divisor = 5;
    let end_x = CX + dx * (divisor - shorten) / divisor;
    let end_y = CY + dy * (divisor - shorten) / divisor;
    draw_line(canvas, CX, CY, end_x, end_y, mark);
}

fn write_time(hour: usize, minute: usize, second: usize) {
    let value = [
        b'0' + (hour / 10) as u8,
        b'0' + (hour % 10) as u8,
        b':',
        b'0' + (minute / 10) as u8,
        b'0' + (minute % 10) as u8,
        b':',
        b'0' + (second / 10) as u8,
        b'0' + (second % 10) as u8,
    ];
    let _ = io::write_all(io::STDOUT, &value);
}

fn write_colored(row: &[u8]) {
    for byte in row {
        match byte {
            b'h' => {
                display::set_color(display::BLUE);
                io::print("o");
            }
            b'm' => {
                display::set_color(display::BLUE);
                io::print("*");
            }
            b's' => {
                display::set_color(display::RED);
                io::print(".");
            }
            _ => {
                display::set_color(display::TEXT);
                let _ = io::write_all(io::STDOUT, core::slice::from_ref(byte));
            }
        }
    }
    display::set_color(display::TEXT);
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
