from pathlib import Path
import sys,shutil
if len(sys.argv)!=2:raise SystemExit('Usage: python3 patch-main.py /path/to/Waveshare_fbcp/src/main.cpp')
p=Path(sys.argv[1]).resolve();backup=p.with_name(p.name+'.usbai-before')
if backup.exists():raise SystemExit('Backup already exists; inspect it before retrying')
shutil.copy2(p,backup);s=p.read_text()
start=s.index('        if (!displayOff && tick() - waitStart > TURN_DISPLAY_OFF_AFTER_USECS_OF_INACTIVITY)')
end=s.index('      }\n    }',start)
old=s[start:end]
assert 'FUTEX_WAIT, 0, 0, 0, 0)' in old
s=s[:start]+'''        const bool inputActive = TimeSinceLastKeyboardPress() < TURN_DISPLAY_OFF_AFTER_USECS_OF_INACTIVITY;
        if (inputActive && displayOff) {
          TurnDisplayOn(); displayOff = false;
        } else if (!inputActive && !displayOff && tick() - waitStart > TURN_DISPLAY_OFF_AFTER_USECS_OF_INACTIVITY) {
          TurnDisplayOff(); displayOff = true;
        }
        // A static GPU image does not wake the futex. Poll HAT input even when dark.
        timespec timeout = {};
        timeout.tv_nsec = 100000000;
        if (programRunning)
          syscall(SYS_futex, &numNewGpuFrames, FUTEX_WAIT, 0, &timeout, 0, 0);
#else
        if (programRunning)
          syscall(SYS_futex, &numNewGpuFrames, FUTEX_WAIT, 0, 0, 0, 0);
#endif
'''+s[end:]
s=s.replace('while (__atomic_load_n(&numNewGpuFrames, __ATOMIC_SEQ_CST) == 0)','while (programRunning && __atomic_load_n(&numNewGpuFrames, __ATOMIC_SEQ_CST) == 0)')
p.write_text(s);print('Patched idle-frame backlight loop')
