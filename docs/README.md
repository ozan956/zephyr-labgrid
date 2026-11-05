# Documentation

- [One board on your desk](quickstart.md) gives you a complete lab on one
  machine to try the module.
- [For Zephyr developers](zephyr-developer.md) explains how to flash, reset
  and run Twister on a board behind a labgrid exporter.
- [For lab owners](lab-owner.md) explains how to expose labgrid places to Zephyr users
  and to Twister.
- [Best practices](best-practices.md) lists what to watch out for.
- [Design notes](design.md) describe how it works inside, for contributors.

How the pieces fit together.

```
developer / CI host                           exporter host
-------------------                           -------------
west flash / west reset -r labgrid            labgrid-exporter
  '-> labgrid API --------------------------> OpenOCD / vendor tool --> probe --> board
twister --device-testing                                                          |
  |-- west flash -r labgrid (as above)                                            |
  '-- labgrid-pty --> labgrid API ----------> ser2net (RFC2217) <--- serial port <-'
                          ^
                          |
                  labgrid-coordinator (places, locks, tags)
```

On the developer side the module adds the `labgrid` west runner and the
`labgrid-pty` console bridge. Zephyr and labgrid are used as they are.
