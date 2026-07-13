Dr Thomas S Ball, 13/07/2026

This is an updated version of the methods described in this manuscript https://www.nature.com/articles/s43016-025-01224-w, updated to take new data into account and to improve pipeline robustness/replicability. This work was undertaken partially on behalf of the Stockholm Environment Institute to feed into the JNCC UK impact indicator toolkit. The primary changes are that this version uses MAPSPAM instead of GAEZ to inform the distribution of production for different agricultural commodities. This version is temporally explicit and is calculated for the years 2000, 2005, 2010, and 2020, using matched input data for each year. Both versions use 'HYDE' for pasture and 'GLW' for animal distributions, though this version uses the appropriate year for each

A major improvement was made in the mapping of 'current' land cover - using an improved algorithm where Martin Jung's 'Global map of terrestrial habitat types' does not agree with crop and pasture distribution according to MAPSPAM or HYDE.

Further improvements are summary statistics for each calculated value (area in question, standard error on the weighted means, number of wild species involved in the calculation, etc). 

The codebase is written almost entirely in Python, relying on the standard library in addition to the requirements that can be found in the 'requirements' file, and which can be installed by running 'pip install -r requirements'. 

Running the files in the order indicated by their names should work to produce the end result, including any neccessary data retrieval. However, one step in the process requires access to a private database version of information that can be found on the IUCN Red List. This component is located in the 'LIFE' subrepository and is not my responsibility. The information used is all publicly available from the Red List website or API, so the process could be replicated with API calls for each species.

At some point this process will be written up in a robust methods document (work in progress).

Please drop me an email (tsb42@cam.ac.uk) if you have any questions!
