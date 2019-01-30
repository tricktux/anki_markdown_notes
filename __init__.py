import logging
from logging.handlers import RotatingFileHandler
import os
import re
from glob import glob

from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo

BASIC_MODEL = "Basic"
REVERSE_MODEL = "Basic (and reversed card)"

DIRECTORY = os.path.dirname(os.path.realpath(__file__))


def init_log():
    """
    Initialize logging.
    Uses by default DIRECTORY
    """

    logger = logging.getLogger("Anki Markdown Notes Log")
    handler = RotatingFileHandler('{}/anki-markdown.log'.format(DIRECTORY),
                              maxBytes=10**6, backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


def process_all_notes(notes_path):
    """
    Read all markdown notes in `notes_path` and load into Anki collection.
    Notes in root folder go to the default deck.
    Notes in subfolders go to a deck named after the corresponding subfolder.
    Any folders in the subfolder are ignored.
    """

    logger = logging.getLogger("Anki Markdown Notes Log")

    deck_counter = {}
    existing_notes_ids = set()
    for markdown_file in glob(os.path.join(notes_path, "*.md")):
        logger.debug('[process_all_notes]: processing default file: "%s"',
                     markdown_file)
        existing_notes_in_file = process_file(markdown_file, "Default")
        deck_counter["Default"] = (
            deck_counter.get("Default", 0) + len(existing_notes_in_file))
        existing_notes_ids.update(existing_notes_in_file)
    for markdown_file in glob(os.path.join(notes_path, "*", "*.md")):
        logger.debug('[process_all_notes]: processing sub decks file: "%s"',
                     markdown_file)
        folder_name = (os.path.basename(os.path.dirname(markdown_file)))
        existing_notes_in_file = process_file(markdown_file, folder_name)
        deck_counter[folder_name] = (
            deck_counter.get(folder_name, 0) + len(existing_notes_in_file))
        existing_notes_ids.update(existing_notes_in_file)

    if not deck_counter:
        showInfo("Failed to find any cards inside: " + notes_path)
        return deck_counter

    deck_counter["DELETED"] = delete_notes(existing_notes_ids)
    if deck_counter["DELETED"]:
        showInfo("Deleted " + notes_path + " notes")

    return deck_counter


def add_note(front, back, tag, model, deck, note_id=None):
    """
    Add note with `front` and `back` to `deck` using `model`.
    If `deck` doesn't exist, it is created.
    If `model` doesn't exist, nothing is done.
    If `note_id` is passed, it is used as the note_id
    """
    model = mw.col.models.byName(model)
    if model:
        mw.col.decks.current()['mid'] = model['id']
    else:
        return None

    # Creates or reuses deck with name passed using `deck`
    did = mw.col.decks.id(deck)
    deck = mw.col.decks.get(did)

    note = mw.col.newNote()
    note.model()['did'] = did

    note.fields[0] = front
    note.fields[1] = back

    if note_id:
        note.id = note_id
    note.addTag(tag)
    mw.col.addNote(note)
    mw.col.save()
    return note.id


def modify_note(note, front, back, tag):
    """
    Modifies given note with given `front`, `back` and `tag`.
    If note with id is not found, do nothing.
    """
    note.fields[0] = front
    note.fields[1] = back
    note.addTag(tag)
    note.flush()
    return note.id


def is_id_comment(line):
    """
    Check if line matches this format <!-- 1510862771508 -->
    """
    id_comment_pattern = re.compile("<!-{2,} *\\d{13,} *-{2,}>")
    return bool(id_comment_pattern.search(line))


def get_id_from_comment(line):
    """
    Get id from comment
    Returns 1510862771508 from <!-- 1510862771508 -->
    """
    id_pattern = re.compile("\\d{13,}")
    return id_pattern.findall(line)[0]


def process_file(file, deck="Default"):
    """
    Go through one markdown file, extract notes and load into Anki collection.
    Writes everything to a .temp file and adds ID comments as necessary.
    Once processing is done, the .temp file is moved to the original file.
    """
    front = []  # list of lines that make up the front of the card
    back = []  # list of lines that make up the back of the card
    model = None
    deck = deck
    current_id = ""
    to_write = []  # buffer to store lines while processing a Note
    # get filename and ignores extension
    tag = os.path.basename(file).split('.')[0]
    # notes in Anki not in this will be deleted at the end
    existing_notes_in_file = set()

    logger = logging.getLogger("Anki Markdown Notes Log")

    def handle_note():
        """
        Determines if current note is new or existing and acts appropriately.
        """
        if not (front and back):
            return False

        front_text, back_text = "<br>".join(front), "<br>".join(back)
        logger.debug('[handle_note]: front: "%s"', format(front_text))
        logger.debug('[handle_note]: back: "%s"', format(back_text))

        # handle special ascii characters
        #  front_text = front_text.decode('utf-8')
        #  back_text = back_text.decode('utf-8')

        if current_id:
            new_id = None
            try:
                note = mw.col.getNote(current_id)
                new_id = modify_note(note, front_text, back_text, tag)
            except:
                new_id = add_note(front_text, back_text, tag, model, deck,
                                  current_id)

                if new_id:
                    # Overwrite in case format was off
                    to_write[-2] = ("<!-- {} -->\n".format(current_id))

        else:
            new_id = add_note(front_text, back_text, tag, model, deck)
            if new_id:
                to_write.insert(
                    len(to_write) - 1, "<!-- {} -->\n".format(new_id))

        temp_file.writelines(to_write)

        if new_id:
            existing_notes_in_file.add(new_id)
            return True  # successfully handled Note
        return False

    temp_file_path = file + ".temp"
    with open(file, "r") as original_file:
        with open(temp_file_path, "w") as temp_file:
            for line in original_file:

                if not (line.startswith("Q:") or line.startswith("QA:")
                        or to_write):
                    temp_file.write(line)
                    continue

                # line is a part of a Note that has to be added to Anki

                to_write.append(line)
                if not line.strip():
                    handle_note()
                    to_write = []
                    front = []
                    back = []
                    current_id = ""
                    model = None
                    continue

                if line.startswith("Q:"):
                    model = BASIC_MODEL
                    front.append(line[2:].strip())
                elif line.startswith("QA:"):
                    model = REVERSE_MODEL
                    front.append(line[3:].strip())
                elif is_id_comment(line):
                    current_id = get_id_from_comment(line)
                elif line.startswith("A:"):
                    back.append(line[2:].strip())
                elif not back:
                    front.append(line.strip())
                else:
                    back.append(line.strip())
            if to_write:
                # Append new line so id comment is on the next line
                to_write[-1] = to_write[-1].strip() + "\n"
            to_write.append("\n")
            handle_note()
    os.remove(file)
    os.rename(temp_file_path, file)
    return existing_notes_in_file


def delete_notes(existing_notes_ids):
    """
    Deletes notes in Anki that aren't in the passed list of
    `existing_notes_ids`
    """
    logger = logging.getLogger("Anki Markdown Notes Log")
    logger.debug('[delete_notes]: note_id: "%s"', existing_notes_ids)
    notes_to_delete = set()
    num_deleted = 0
    all_decks = mw.col.decks.allNames()
    for deck in all_decks:
        for cid in mw.col.findNotes("deck:" + deck):
            # cid is of type long but existing_notes_ids are string
            if str(cid) not in existing_notes_ids:
                notes_to_delete.add(cid)
                num_deleted += 1

    logger.debug('[delete_notes]: num_deleted = %d', num_deleted)
    logger.debug('[delete_notes]: notes_to_delete = %s', notes_to_delete)
    mw.col.remNotes(notes_to_delete)
    return num_deleted


def write_note(note, deck_file):
    """
    Write lines to the markdown file from the note object.
    '<br>' in the front/back are converted to '\n'
    """
    logger = logging.getLogger("Anki Markdown Notes Log")
    logger.error('[write_note]: deck_file: "%s"', deck_file)

    if note.model()["name"] == BASIC_MODEL:
        q_prefix = "Q:"
    elif note.model()["name"] == REVERSE_MODEL:
        q_prefix = "QA:"
    else:
        logger.error('[write_note]: Unsupported model: "%s"',
                     note.model()["name"])
        return  # Unsupported model

    note_front = note.fields[0].replace("<br>", "\n").encode('utf-8')
    logger.debug('\tWriting front of note:\n\t\t"%s"\n', format(note_front))
    deck_file.write("{} {}\n".format(q_prefix, note_front))

    note_back = note.fields[1].replace("<br>", "\n").encode('utf-8')
    logger.debug('\tWriting back of note:\n\t\t"%s"\n', format(note_back))
    deck_file.write("A: {}\n".format(note_back))

    # note_back = "A: {}\n".format(note.fields[1].replace("<br>", "\n"))
    # deck_file.write(note_back.encode('utf-8'))
    deck_file.write("<!-- {} -->\n\n".format(note.id))


def export_all_notes(notes_path):
    """
    Exports all notes to markdown files in a Notes folder in 'notes_path'.
    Aborts if 'Notes' folder already exists.
    For deck 'DeckName', a folder 'DeckName' is created and all the notes
    in that deck are stored in 'DeckName.md' in that folder.
    """
    notes_path = os.path.join(notes_path, "Notes")
    if os.path.exists(notes_path):
        showInfo("Aborting - 'Notes' folder already exists")
        return 0

    os.makedirs(notes_path)
    all_decks = mw.col.decks.allNames()
    for deck in all_decks:
        deck_folder = os.path.join(notes_path, deck)
        os.makedirs(deck_folder)
        with open(os.path.join(deck_folder, deck + ".md"), "w") as deck_file:
            deck_file.write("# {} \n\n".format(deck))
            for cid in mw.col.findNotes("deck:" + deck):
                note = mw.col.getNote(cid)
                write_note(note, deck_file)

    return all_decks


def import_notes_ui():
    """
    Lets user pick a directory and imports Notes from it.
    """
    widget = QWidget()
    notes_path = str(QFileDialog.getExistingDirectory(widget, "Pick Notes Folder"))
    if notes_path:
        deck_counter = process_all_notes(notes_path)
        widget.show()
        showInfo("Notes handled in each deck - " + str(deck_counter))


def export_notes_ui():
    """
    Lets user pick a directory and exports Notes to it.
    """
    widget = QWidget()
    notes_path = str(QFileDialog.getExistingDirectory(widget, "Pick Notes Folder"))
    if notes_path:
        expoorted_decks = export_all_notes(notes_path)
        if expoorted_decks:
            widget.show()
            showInfo("Exported these decks - " + ", ".join(expoorted_decks))


init_log()

export_action = QAction("Export to Markdown Notes", mw)
export_action.triggered.connect(export_notes_ui)
mw.form.menuTools.addAction(export_action)

import_action = QAction("Import from Markdown Notes", mw)
import_action.triggered.connect(import_notes_ui)
mw.form.menuTools.addAction(import_action)
