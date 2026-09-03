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

if [ ! -f "$instance_dir/config/config.toml" ]; then
    mkdir -p "$instance_dir"
    cp -a "$template_dir/." "$instance_dir/"
    echo "Initialized NovariusIRC instance: $instance_name" >&2
fi

config_selected=false
expect_value=false
for argument in "$@"; do
    if [ "$expect_value" = true ]; then
        expect_value=false
        continue
    fi
    case "$argument" in
        --config|-c|--instance|--instancedir)
            config_selected=true
            expect_value=true
            ;;
        --config=*|--instance=*|--instancedir=*)
            config_selected=true
            ;;
        --ctl|--restore-database)
            expect_value=true
            ;;
        -*)
            ;;
        *)
            # The CLI accepts one positional configuration path.
            config_selected=true
            ;;
    esac
done

if [ "$config_selected" = false ]; then
    # Preserve commands such as --check-config and --version after the default
    # instance configuration has been selected.
    set -- --config "$instance_dir/config" "$@"
fi

exec /app/venv/bin/novariusirc "$@"
