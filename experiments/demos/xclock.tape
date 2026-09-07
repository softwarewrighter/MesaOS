Output experiments/demos/xclock.gif

Set Shell "bash"
Set FontSize 18
Set Width 900
Set Height 620
Set TypingSpeed 35ms
Set PlaybackSpeed 1
Set Theme { "name": "Catppuccin Mocha", "background": "#191724" }

Type "./experiments/build.sh"
Enter
Sleep 2s

Type "./experiments/target/x86_64-unknown-none/release/xclock"
Enter
Sleep 5s
