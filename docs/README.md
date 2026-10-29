# Documentation

- [For Zephyr developers](zephyr-developer.md): flash and test your build on a
  board that lives behind a labgrid exporter.
- [For lab owners](lab-owner.md): expose your labgrid places to Zephyr users
  and to Twister.
- [Best practices](best-practices.md): what we learned while running Twister
  through labgrid.

How the pieces fit together:

```
developer / CI host                         exporter host
-------------------                         -------------
west build                                  labgrid-exporter
west flash -r labgrid ----> labgrid API ---> OpenOCD / pyOCD / vendor tool --> probe --> board
twister --device-testing                                                                |
  |-- west flash -r labgrid (as above)                                                  |
  |-- labgrid-pty ---------> labgrid API ---> ser2net (RFC2217) <------ serial port <---+
                                 ^
                                 |
                         labgrid-coordinator (place locks, resource matching)
```

Only two things are added on the developer side: the `labgrid` west runner
and the `labgrid-pty` script. Zephyr and labgrid themselves are unchanged.
