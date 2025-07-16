# WT64
![alt text](https://github.com/KillerFeature/WT64/raw/master/WT64_hero.png)
A Commodore 64 Experience for Windows Terminal

![Video](https://github.com/KillerFeature/WT64/raw/master/video.gif "Video")

### FEATURES
- Native C64 style commands like `LOAD "$",8`
- Native C64 LIST layout for directory listing with size reporting and Blocks free indication
- Startup screen with actual PowerShell version and memory reporting

### SUPPORTED COMMANDS
- **`LIST <path>`** Lists the files in local or path directory in C64 disk style
- **`LOAD "$",8`** Shows the classic loading sequence
- **`SYS64738`** Shows the opening prompt
- **`EDIT <filename>`** Alias for Nano

### PREREQUISITES
1. [Windows Terminal](https://aka.ms/terminal) © Microsoft
2. [PowerShell 7](https://github.com/PowerShell/PowerShell/releases/latest) © Microsoft
3. [C64 font](https://www.dafont.com/commodore-64.font) © Devin Cook

### INSTALLATION
0. Make sure the prerequisites are installed
1. Clone the repo
2. Move or copy the files `commands.ps1`, `icon.png`, `P64_bg.png` & `reset.ps1` to a folder of your liking  
I use a folder `WT64` in `Program Files`  
3. Open `Profile.json`, cut & paste the **list item** and **colorscheme** into your Windows Terminal Settings file  
`%LOCALAPPDATA%\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json`
4. Replace where it says `[INSERT YOUR REPO PATH HERE]` with the path of the folder you created in step 2 and save
5. Start Windows Terminal & open a WT64 terminal

### BACKGROUND ISSUES
The standard background doesn’t always scale properly, you can use the `P64_bg.svg` to create a new background that will have a 75px border and fit your screenresolution by following these steps:
#### 1. Edit SVG
Open the SVG in any text-editor, edit the width and height on the first line in the viewBox attribute & third line in the width and height attributes and save  
It should be your full screen width and height minus taskbar (40px) and window header (36px)  
If you don’t use the taskbar or have it on the side of your screen adjust the height and width in the SVG accordingly
#### 2. Convert the SVG to PNG
Open the updated SVG in an SVG capable photo-editor and save as `P64_bg.png`

I use [PhotoPea](https://photopea.com) for this, online, easy & free!
- Drag the SVG-file onto center area or use `File > Open...`
- Select `File > Export as > PNG`
- Click `Save`
- If necessary rename the PNG-file to `P64_bg.png`
#### 3. Replace the background
Replace the current background with this newly created one by overwriting the current one in the location you have stored WT64
#### 4. Done!
Restart Windows Terminal and see the new background in action