One blocker remains: **display-name validation and mapping disagree.** The validator accepts a response with both `title` and `source_name` absent by using `clip_id`, but mapping accesses `nuevo.title` and `nuevo.source_name` directly. Under strict template handling, that can fail after validation instead of taking fallback.

In both artifacts, use the same safe expression during mapping:

```jinja
{{ nuevo.get('title') or nuevo.get('source_name') or nuevo.get('clip_id') }}
```

Add a production strict-template test with both name fields absent, checking validation **and mapping**. The outer declarations and isolated selftest failure path are otherwise acceptable.

CONSENSUS: NO
