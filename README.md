# PSPPEEPS Adhoc Server  
It's PPSSPP Adhoc Server - but only for Phantasy Star Portable.  
Other features include Alphine 3.23 update and an exporter for metrics.  

# Supported Games  
```
		"ULUS10410", /* Phantasy Star Portable US */
		"ULES01218", /* Phantasy Star Portable EU/AU */
		"ULJM05309", /* Phantasy Star Portable JP */
		"ULJM08023", /* Phantasy Star Portable JP PSP the Best */

		"ULUS10529", /* Phantasy Star Portable 2 US */
		"ULES01439", /* Phantasy Star Portable 2 EU/AU */
		"ULJM05493", /* Phantasy Star Portable 2 JP */
		"NPJH50043", /* Phantasy Star Portable 2 JP PSN */
		"ULJM08030", /* Phantasy Star Portable 2 JP PSP the Best */

		"ULJM05732", /* Phantasy Star Portable 2 Infinity JP */
		"NPJH50332", /* Phantasy Star Portable 2 Infinity JP PSN */
```

# Launch
```
docker run --port 27312:27312 -it ghcr.io/souler/ppsspp-adhoc
```

## Contributors
- [Kyhel](https://github.com/Kyhel) for sharing the original PPSSPP AdhocServer source code on [the forums](http://forums.ppsspp.org/showthread.php?tid=3595&pid=59021#pid59021)


## Building
- Make sure you have installed the sqlite-libs dependencies.
