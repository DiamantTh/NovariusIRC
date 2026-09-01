#!/bin/sh
# Seed a named instance on its first container start, then execute NovariusIRC.
set -eu

instance_name="${NOVARIUSIRC_INSTANCE:-example}"
case "$instance_name" in
    "" | .* | *"/"* | *"\\"*)
        echo "NOVARIUSIRC_INSTANCE must be a simple instance directory name" >&2
        exit 64
        ;;
esac

instance_dir="/app/instances/$instance_name"
template_dir="/opt/novariusirc-instance-template"

if [ ! -f "$instance_dir/config.toml" ]; then
    mkdir -p "$instance_dir"
    cp -a "$template_dir/." "$instance_dir/"
    echo "Initialized NovariusIRC instance: $instance_name" >&2
fi

if [ "$#" -eq 0 ]; then
    set -- --config "$instance_dir/config.toml"
fi

exec /app/bin/novariusirc "$@"
