from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from dmxreplay.metadata import Manifest, UniverseMapping, UnsupportedManifestVersionError

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "dmxreplay" / "metadata" / "schema.json"
)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _sample_manifest(**overrides) -> Manifest:
    kwargs = dict(
        encoding="grayscale",
        fps=30.0,
        vfr=True,
        timestamp_resolution_ns=1000,
        width=512,
        height=2,
        universes=[
            UniverseMapping(row=0, protocol="Art-Net", universe=1, net=0, subnet=0),
            UniverseMapping(row=1, protocol="sACN", universe=5),
        ],
        created_at="2026-08-27T00:00:00Z",
        duration_seconds=5.0,
        recorder={"name": "dmxreplay-recorder", "version": "0.1.0-dev"},
    )
    kwargs.update(overrides)
    return Manifest(**kwargs)


def test_schema_json_is_valid_and_loads():
    schema = _schema()
    jsonschema.Draft202012Validator.check_schema(schema)


def test_sample_manifest_validates_against_schema():
    manifest = _sample_manifest()
    jsonschema.validate(instance=manifest.to_dict(), schema=_schema())


def test_manifest_json_round_trip():
    manifest = _sample_manifest(show_name="Test Show")
    restored = Manifest.from_json(manifest.to_json())
    assert restored.to_dict() == manifest.to_dict()


def test_manifest_preserves_unknown_fields_on_round_trip():
    data = _sample_manifest().to_dict()
    data["some_future_field"] = {"nested": True}
    manifest = Manifest.from_dict(data)
    assert manifest.extra_fields["some_future_field"] == {"nested": True}
    # Round-tripping again must not drop it (SPECIFICATION.md §10.4).
    assert manifest.to_dict()["some_future_field"] == {"nested": True}


def test_manifest_rejects_wrong_format_marker():
    with pytest.raises(ValueError):
        _sample_manifest().__class__(
            **{**_sample_manifest().__dict__, "format": "NotDMXReplay"}
        )


def test_manifest_rejects_unsupported_major_version():
    with pytest.raises(UnsupportedManifestVersionError):
        _sample_manifest(version="2.0")


def test_manifest_accepts_newer_minor_version_within_same_major():
    manifest = _sample_manifest(version="1.7")
    assert manifest.version == "1.7"


def test_manifest_height_must_match_universe_count():
    with pytest.raises(ValueError):
        _sample_manifest(height=5)  # only 2 entries in universes[]


def test_manifest_rows_must_be_contiguous_from_zero():
    with pytest.raises(ValueError):
        _sample_manifest(
            universes=[
                UniverseMapping(row=0, protocol="Art-Net", universe=1, net=0, subnet=0),
                UniverseMapping(row=2, protocol="sACN", universe=5),  # gap: no row 1
            ]
        )


def test_artnet_universe_mapping_requires_net_and_subnet():
    with pytest.raises(ValueError):
        UniverseMapping(row=0, protocol="Art-Net", universe=1)


def test_artnet_port_address_conversion_round_trips():
    # Worked example from docs/ARTNET.md §1/§2.
    mapping = UniverseMapping(row=0, protocol="Art-Net", universe=3, net=1, subnet=2)
    port_address = mapping.port_address()
    assert port_address == (1 << 8) | (2 << 4) | 3
    net = (port_address >> 8) & 0x7F
    subnet = (port_address >> 4) & 0x0F
    universe = port_address & 0x0F
    assert (net, subnet, universe) == (1, 2, 3)


def test_sacn_universe_mapping_rejects_out_of_range():
    with pytest.raises(ValueError):
        UniverseMapping(row=0, protocol="sACN", universe=0)
    with pytest.raises(ValueError):
        UniverseMapping(row=0, protocol="sACN", universe=64000)


def test_sparse_universe_worked_example_from_spec():
    # Source universes (Port-Addresses) {1, 5, 17, 42} packed into contiguous
    # rows {0,1,2,3}, per docs/SPECIFICATION.md §7's worked example and
    # docs/ARTNET.md §1.1 (flattened Port-Address, not the raw Universe field).
    source_port_addresses = [1, 5, 17, 42]
    mapping = [
        UniverseMapping.from_artnet_port_address(row=row, port_address=pa)
        for row, pa in enumerate(source_port_addresses)
    ]
    manifest = _sample_manifest(height=4, universes=mapping)
    assert [u.port_address() for u in manifest.universes] == source_port_addresses
    assert [u.row for u in manifest.universes] == [0, 1, 2, 3]
    # Port-Address 17 must decompose to Net=0, Sub-Net=1, Universe=1 -- not
    # Universe=17, which would be out of the raw field's 0-15 range.
    assert (mapping[2].net, mapping[2].subnet, mapping[2].universe) == (0, 1, 1)
