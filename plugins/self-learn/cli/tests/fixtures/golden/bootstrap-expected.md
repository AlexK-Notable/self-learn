# A markerless target

Some authored prose. No self-learn markers anywhere yet.

<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->
- **When about to edit a `.storage/*.json` file while Home Assistant is running:** stop the HA container first. HA caches `.storage` in memory and rewrites it on shutdown, so a live edit is silently clobbered. *(lrn-4c1e9a2f)*
- A config-entry reload does not re-read `data.host`. *(lrn-77ab01cd)*
<!-- self-learn:end -->
