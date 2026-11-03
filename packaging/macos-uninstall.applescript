-- Compiled into "Uninstall Studio 87 Gear Updater.app" by the release workflow (osacompile). Installed to /Applications by the .pkg.
-- Removes the updater itself. Your plugins and presets are never touched; its own settings are kept unless you choose to delete them.
set dataDir to (POSIX path of (path to application support folder from user domain)) & "Studio 87/Gear Updater"
display dialog "Remove Studio 87 Gear Updater from this Mac?" & return & return & "This deletes the app and this uninstaller. Plugins you installed with it stay." buttons {"Cancel", "Remove"} default button "Cancel" with icon caution
set keepData to true
tell application "System Events" to set hasData to (exists folder dataDir)
if hasData then
	set r to display dialog "Also delete the updater's settings and list of installed versions?" & return & return & dataDir buttons {"Keep them", "Delete them"} default button "Keep them" with icon caution
	if button returned of r is "Delete them" then set keepData to false
end if
set cmds to "rm -rf '/Applications/Studio 87 Gear Updater.app' '/Applications/Uninstall Studio 87 Gear Updater.app' '/Library/Application Support/Studio 87/Gear Updater'; "
set cmds to cmds & "rmdir '/Library/Application Support/Studio 87' 2>/dev/null; for p in $(pkgutil --pkgs | grep '^io.github.speakingcolors.studio87gearupdater'); do pkgutil --forget $p; done"
do shell script cmds with administrator privileges
if keepData is false then
	do shell script "rm -rf " & quoted form of dataDir
	do shell script "rmdir " & quoted form of (POSIX path of (path to application support folder from user domain) & "Studio 87") & " 2>/dev/null; true"
end if
set doneMsg to "Studio 87 Gear Updater was removed."
if keepData then set doneMsg to doneMsg & return & "Its settings were kept."
display dialog doneMsg buttons {"OK"} default button "OK"
