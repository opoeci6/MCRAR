MCRAR - preview build for Windows 10/11 (64-bit)
================================================

MCRAR finds music from a text description ("calm piano for a rainy city level")
and runs entirely on your PC. This preview needs no installation, no Python and
no admin rights.

First steps
-----------
1. Unzip the whole folder to a short path, for example C:\MCRAR. Avoid very
   deep folders: some of the bundled files have long names.
2. Double-click MCRAR.cmd. A window opens and, after a few seconds, your
   browser shows MCRAR. If Windows blocks the file (SmartScreen, "Windows
   protected your PC"), click "More info" and then "Run anyway". If the zip
   was downloaded, you can also right-click it before unzipping, open
   Properties and tick "Unblock".
3. The first start downloads the search model once (about 0.8 GB), so it needs
   an internet connection and a few minutes. Later starts are much faster and
   work offline.
4. Close the window to stop MCRAR.

Adding music
------------
- Free sources: in the app open Settings, then API keys, and paste a free
  Jamendo client id (devportal.jamendo.com) or a free Freesound API key
  (freesound.org/apiv2/apply). Then use Library, then Add music, to import
  tracks by tags or search.
- Single tracks: in Library, Add music, By link, paste Jamendo or Freesound
  track links.
- Your own music: in Library, Add music, Local folder, add a folder of audio
  files on this PC. Set the folder's licence there.
- MCRAR does not upload your files anywhere.

Options
-------
Run MCRAR.cmd from a command prompt to pass options:
  MCRAR.cmd --port 8010     use another port (default 8000)
  MCRAR.cmd --no-open       do not open the browser

Where things are stored
-----------------------
Everything stays in this folder: the music library (data\), settings
(config\), downloaded models (.cache\) and API keys (.secrets\). Nothing is
written to your user profile or the registry. To remove MCRAR, delete the
folder. To move it, close the window and move the whole folder.

Licences
--------
The source code is MIT-licensed. The app as a whole is for non-commercial use
only, because some of the models and datasets it uses are non-commercial. See
NOTICE.md in this folder for details.

Project page and source: https://github.com/opoeci6/MCRAR
