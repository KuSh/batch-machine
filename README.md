<h1 align="center">OA Machine</h1>

Scripts for performing ETL on a single source, passing the end result to the [openaddresses/batch](https://github.com/openaddresses/batch) service
Uses [OpenAddresses](https://github.com/openaddresses/openaddresses) data sources to work.

## Status

This code is being used to process the complete OA dataset on a weekly and on-demand
basis, with output visible at [batch.openaddresses.io](https://batch.openaddresses.io).

These scripts are wrapped by the main [openaddresses/batch](https://github.com/openaddresses/batch) processor.

## Use

It is highly recommended to use this tool via the provided docker file - using an unsupported/untested version
of GDAL (the core geospatial library) will result in widely varying results.

Should you run this in a virtual env, install [Tippecanoe](https://github.com/mapbox/tippecanoe.git) and [GDAL](https://pypi.org/project/GDAL/)
before use.

### Docker

```
docker build -t batch-machine .
```
