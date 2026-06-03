# PSPPEEPS Adhoc Server  
It's [PPSSPP Adhoc Server](https://github.com/Souler/ppsspp-adhoc-server) - but only for Phantasy Star Portable.  
No ZeroTier or other third-party VPN required.  
Features include Alpine 3.23, [aemu_postoffice](https://github.com/Kethen/aemu_postoffice), and an exporter for metrics.  
  
You can easily fork and edit this to allow your own specific list of games or remove the allowlist entirely.

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
docker compose up -d --build
```

## Contributors
- [Kyhel](https://github.com/Kyhel) for sharing the original PPSSPP AdhocServer source code on [the forums](http://forums.ppsspp.org/showthread.php?tid=3595&pid=59021#pid59021)  

## Play on PSO Peeps  
Server addresses:  
US Server: `108.175.11.140`  
EU Server:  `65.21.79.231`  

Add one of the above addresses above in PPSSPP's Network -> Ad Hoc Multiplayer settings.  
Set `Try to use server-provided packet relayer` to Yes.  
Assign yourself a nickname.  
