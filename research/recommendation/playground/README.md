# Ataraxia Research Playground

From the repository root, with the existing research Python environment and
restored local PostgreSQL catalogue available, install the dashboard dependency
and launch the app.

```sh
.venv/bin/python -m pip install -r research/recommendation/playground/requirements.txt
.venv/bin/python -m streamlit run research/recommendation/playground/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open the local URL shown by Streamlit. The catalogue uses the existing
read-only Unix socket loader. Previews come from files under `data/` with an
unambiguous canonical video ID as the filename stem. Playback depends on the
browser's codec support.

Choose onboarding categories and select **Reset user** to apply them. Select
**Start new session** to apply the feedback mode or simulator seeds while
retaining LTM. The simulator generates feedback from its own seeded profile,
whose public categories appear on screen. The selected onboarding categories
initialize the recommendation memories independently.

Choose a video from any of the four outputs and submit manual feedback or
sample the simulator. The unified adapter refreshes all four pools after each
interaction. Current and Stable show STM and LTM Top-10 respectively, with the
same session exclusions. Recovery and Diverse use the existing Stage 2 searches
with Current as their reference. The dashboard shows availability, pairwise
overlap, consecutive rankings, drift, feedback history and category counts.

Memory lives in the browser's Streamlit session state across app reruns. A new
research session resets STM and clears the current feedback history and
exclusions. A user reset also reinitializes LTM. Browser disconnection or
server restart can discard this in-memory state.

```sh
.venv/bin/python -B -m unittest discover -s research/recommendation/tests
```
