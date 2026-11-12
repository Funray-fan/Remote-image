# Stage 2 synthetic map fixture

All images, polygons, classes and confidence values are synthetic. They test the C3 interface only and do not demonstrate model accuracy or real damage.

- Six buildings cover the five approved classes.
- Threshold 0.90 displays DEMO-001 and DEMO-004.
- RGB GeoTIFFs use EPSG:3857 to exercise reprojection.
- The event matches the stage1_synthetic flood fixture so that overlays can be tested.
- DamageResult and vector properties follow the existing v1 JSON schemas.
- Artifact paths are relative to damage_result.json.
- metadata.fixture_only and meta.parameters.fixture_only identify this test fixture.

No xBD imagery, model weights or real assessment outputs are included.
