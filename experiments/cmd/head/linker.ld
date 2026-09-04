OUTPUT_FORMAT("elf64-x86-64")
OUTPUT_ARCH(i386:x86-64)
ENTRY(_start)

PHDRS
{
    text PT_LOAD FLAGS(5); /* read + execute */
    data PT_LOAD FLAGS(6); /* read + write */
}

SECTIONS
{
    . = 0x400000;
    .text : ALIGN(4096) {
        *(.text .text.*)
    } :text
    .rodata : ALIGN(4096) {
        *(.rodata .rodata.*)
    } :text
    .data : ALIGN(4096) {
        *(.data .data.*)
    } :data
    .bss : ALIGN(4096) {
        *(.bss .bss.*)
        *(COMMON)
    } :data
    /DISCARD/ : {
        *(.comment)
        *(.eh_frame .eh_frame_hdr)
        *(.note.*)
    }
}
