"""Loaders. One module per upstream source.

Contract for every public loader in this subpackage:
  * fully typed signature;
  * docstring names the source URL, the licence and the data vintage
    (release/version or download date);
  * docstring states the publication lag and therefore the earliest
    timestamp at which the returned values were knowable;
  * returns a frame indexed (or keyed) by UTC timestamp -- never local time.

Planned modules: epc.py, neso.py, elexon.py, national_gas.py,
weather_forecast.py, weather_reanalysis.py, ons_geography.py
"""
