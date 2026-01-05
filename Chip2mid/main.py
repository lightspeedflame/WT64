import tkinter as tk
import os

# --- Dependency Check ---
try:
    from PIL import ImageTk, Image
except ImportError:
    # Pillow is not installed. Create a simple window to show an error message.
    def show_pillow_error():
        root = tk.Tk()
        root.title("Error: Missing Dependency")
        message = "The 'Pillow' library is required to display PNG images.\n\n" \
                  "Please install it by running this command in your terminal:\n" \
                  "pip install Pillow"
        label = tk.Label(root, text=message, justify=tk.LEFT, padx=10, pady=10)
        label.pack(expand=True)
        root.geometry("400x120")
        root.mainloop()
    show_pillow_error()
    exit() # Exit the script if Pillow is not found

# --- Constants ---
IMAGE_FILENAME = "Futuristic chiptune converter interface.png"
WINDOW_TITLE = "Chiptune to MIDI Converter"

def main():
    """
    Main function to create and run the Tkinter application.
    """
    # --- Create the main window ---
    root = tk.Tk()
    root.title(WINDOW_TITLE)

    # --- Load and display the background image or a message ---
    try:
        # Check if the image file exists in the current directory
        if not os.path.exists(IMAGE_FILENAME):
            raise FileNotFoundError() # Raise specific error to be caught below

        # Open the image using Pillow
        pil_image = Image.open(IMAGE_FILENAME)

        # Convert the Pillow image to a Tkinter PhotoImage
        bg_image = ImageTk.PhotoImage(pil_image)

        # Get image dimensions to set the window size
        window_width = pil_image.width
        window_height = pil_image.height
        root.geometry(f"{window_width}x{window_height}")

        # Prevent window resizing
        root.resizable(False, False)

        # Create a label to hold the image
        background_label = tk.Label(root, image=bg_image)
        background_label.place(x=0, y=0, relwidth=1, relheight=1)

        # Keep a reference to the image to prevent it from being garbage collected
        background_label.image = bg_image

    except FileNotFoundError:
        # This error occurs if the file doesn't exist.
        message = f"Error: The image file '{IMAGE_FILENAME}' was not found.\n" \
                  "Please make sure the file is in the 'Chip2mid' folder."
        label = tk.Label(root, text=message, justify=tk.LEFT, padx=10, pady=10)
        label.pack(expand=True)
        root.geometry("400x100")

    except Exception as e:
        # Catch other potential errors (e.g., corrupt image file)
        message = f"An error occurred while loading the image:\n{e}\n\n" \
                  f"Please ensure '{IMAGE_FILENAME}' is a valid image file."
        label = tk.Label(root, text=message, justify=tk.LEFT, padx=10, pady=10)
        label.pack(expand=True)
        root.geometry("400x120")

    # --- Start the Tkinter event loop ---
    root.mainloop()

if __name__ == "__main__":
    main()
