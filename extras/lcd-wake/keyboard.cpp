#include <linux/input.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <string>
#include <vector>
#include "config.h"
#include "keyboard.h"
#include "util.h"
#include "tick.h"

#if defined(BACKLIGHT_CONTROL_FROM_KEYBOARD) && defined(TURN_DISPLAY_OFF_AFTER_USECS_OF_INACTIVITY)
#define READ_KEYBOARD_ENABLED
#endif

struct WakeInput { std::string path; int fd; };
static std::vector<WakeInput> wakeInputs;
static uint64_t lastScan = 0, lastInput = 0;

static void ScanInputs()
{
#ifdef READ_KEYBOARD_ENABLED
  DIR *dir = opendir("/dev/input");
  if (!dir) return;
  struct dirent *entry;
  while ((entry = readdir(dir))) {
    if (strncmp(entry->d_name, "event", 5)) continue;
    std::string path = std::string("/dev/input/") + entry->d_name;
    bool known = false;
    for (size_t i = 0; i < wakeInputs.size(); ++i) if (wakeInputs[i].path == path) known = true;
    if (known) continue;
    int fd = open(path.c_str(), O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) continue;
    char name[256] = {};
    if (ioctl(fd, EVIOCGNAME(sizeof(name)), name) >= 0 &&
        (!strcmp(name,"LCD HAT Buttons Keyboard") || !strcmp(name,"LCD HAT Joystick Mouse"))) {
      WakeInput input; input.path=path; input.fd=fd; wakeInputs.push_back(input);
      printf("Backlight wake input: %s (%s)\n",name,path.c_str()); fflush(stdout);
    } else close(fd);
  }
  closedir(dir);
#endif
}

void OpenKeyboard() { lastInput=tick(); lastScan=0; ScanInputs(); }

int ReadKeyboard()
{
  int activity=0;
#ifdef READ_KEYBOARD_ENABLED
  uint64_t now=tick();
  if (!lastScan || now-lastScan>=2000000) { lastScan=now; ScanInputs(); }
  for (size_t i=0; i<wakeInputs.size();) {
    struct input_event events[32]; ssize_t size;
    while ((size=read(wakeInputs[i].fd,events,sizeof(events)))>0) {
      for (size_t j=0;j<(size_t)size/sizeof(events[0]);++j)
        if ((events[j].type==EV_KEY && events[j].code!=0) ||
            (events[j].type==EV_REL && events[j].value!=0)) ++activity;
    }
    if (size==0 || (size<0 && errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)) {
      close(wakeInputs[i].fd); wakeInputs.erase(wakeInputs.begin()+i);
    } else ++i;
  }
#endif
  return activity;
}

void CloseKeyboard() { for(size_t i=0;i<wakeInputs.size();++i)close(wakeInputs[i].fd);wakeInputs.clear(); }

uint64_t TimeSinceLastKeyboardPress(void)
{
#ifdef READ_KEYBOARD_ENABLED
  uint64_t now=tick();if(ReadKeyboard())lastInput=now;return now-lastInput;
#else
  return UINT64_MAX;
#endif
}
