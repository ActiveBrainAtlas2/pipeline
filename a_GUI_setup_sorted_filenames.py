import os
import sys
import argparse

from PyQt5.QtCore import *
from PyQt5.QtGui import QFont, QIntValidator, QBrush, QColor, QPixmap
from PyQt5.QtWidgets import (QWidget, QApplication, QGridLayout, QLineEdit,
                             QPushButton, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QFrame, QComboBox,
                             QMessageBox)

from utilities.sqlcontroller import SqlController
from utilities.file_location import FileLocationManager

class ImageViewer(QGraphicsView):
    def __init__(self, parent):
        super(ImageViewer, self).__init__(parent)
        self.zoom = 0
        self.empty = True
        self.scene = QGraphicsScene(self)
        self.photo = QGraphicsPixmapItem()

        self.scene.addItem(self.photo)
        self.setScene(self.scene)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor(30, 30, 30)))
        self.setFrameShape(QFrame.NoFrame)

    def set_photo(self, pixmap=None):
        self.zoom = 0
        if pixmap and not pixmap.isNull():
            self.empty = False
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.photo.setPixmap(pixmap)
        else:
            self.empty = True
            self.setDragMode(QGraphicsView.NoDrag)
            self.photo.setPixmap(QPixmap())
        self.fitInView()

    def toggle_drag_mode(self):
        if self.dragMode() == QGraphicsView.ScrollHandDrag:
            self.setDragMode(QGraphicsView.NoDrag)
        elif not self.photo.pixmap().isNull():
            self.setDragMode(QGraphicsView.ScrollHandDrag)

    def fitInView(self, scale=True):
        rect = QRectF(self.photo.pixmap().rect())
        if not rect.isNull():
            self.setSceneRect(rect)
            if not self.empty:
                unity = self.transform().mapRect(QRectF(0, 0, 1, 1))
                self.scale(1 / unity.width(), 1 / unity.height())
                viewrect = self.viewport().rect()
                scenerect = self.transform().mapRect(rect)
                factor = min(viewrect.width() / scenerect.width(),
                             viewrect.height() / scenerect.height())
                self.scale(factor, factor)
            self.zoom = 0
        else:
            print('RECT IS NULL')

    def wheelEvent(self, event):
        if not self.empty:
            if event.angleDelta().y() > 0:
                factor = 1.25
                self.zoom += 1
            else:
                factor = 0.8
                self.zoom -= 1

            if self.zoom > 0:
                self.scale(factor, factor)
            elif self.zoom == 0:
                self.fitInView()
            else:
                self.zoom = 0


class GUISortedFilenames(QWidget):

    def __init__(self, stack, parent=None):
        super(GUISortedFilenames, self).__init__(parent)

        # create a dataManager object
        self.sqlController = SqlController()
        self.stack = stack
        self.fileLocationManager = FileLocationManager(self.stack)
        self.sqlController.get_animal_info(self.stack)

        self.valid_sections = self.sqlController.get_valid_sections(stack)
        self.valid_section_keys = sorted(list(self.valid_sections))

        #self.curr_section_index = len(self.valid_section_keys) // 2
        self.curr_section_index = 0
        self.curr_section = None

        self.init_ui()

        self.dd.currentIndexChanged.connect(lambda: self.click_button(self.dd))
        self.b_left.clicked.connect(lambda: self.click_button(self.b_left))
        self.b_right.clicked.connect(lambda: self.click_button(self.b_right))
        self.b_remove.clicked.connect(lambda: self.click_button(self.b_remove))
        self.b_help.clicked.connect(lambda: self.click_button(self.b_help))
        self.b_done.clicked.connect(lambda: self.click_button(self.b_done))

        self.set_curr_section(self.curr_section_index)

    def init_ui(self):
        self.font_h1 = QFont("Arial", 32)
        self.font_p1 = QFont("Arial", 16)

        # Set Layout and Geometry of Window
        self.grid_top = QGridLayout()
        self.grid_body_upper = QGridLayout()
        self.grid_body = QGridLayout()
        self.grid_body_lower = QGridLayout()
        self.grid_bottom = QGridLayout()
        self.grid_blank = QGridLayout()

        self.resize(1600, 1100)

        ### VIEWER ### (Grid Body)
        self.viewer = ImageViewer(self)

        ### Grid TOP ###
        # Static Text Field (Title)
        self.e1 = QLineEdit()
        self.e1.setValidator(QIntValidator())
        self.e1.setAlignment(Qt.AlignCenter)
        self.e1.setFont(self.font_h1)
        self.e1.setReadOnly(True)
        self.e1.setText("Setup Sorted Filenames")
        self.e1.setFrame(False)
        self.grid_top.addWidget(self.e1, 0, 0)
        # Button Text Field
        self.b_help = QPushButton("HELP")
        self.b_help.setDefault(True)
        self.b_help.setEnabled(True)
        self.b_help.setStyleSheet("color: rgb(0,0,0); background-color: rgb(250,250,250);")
        self.grid_top.addWidget(self.b_help, 0, 1)

        ### Grid BODY UPPER ###
        # Static Text Field
        self.e4 = QLineEdit()
        self.e4.setAlignment(Qt.AlignCenter)
        self.e4.setFont(self.font_p1)
        self.e4.setReadOnly(True)
        self.e4.setText("Filename: ")
        # self.e4.setStyleSheet("color: rgb(250,50,50); background-color: rgb(250,250,250);")
        self.grid_body_upper.addWidget(self.e4, 0, 2)
        # Static Text Field
        self.e5 = QLineEdit()
        self.e5.setAlignment(Qt.AlignCenter)
        self.e5.setFont(self.font_p1)
        self.e5.setReadOnly(True)
        self.e5.setText("Section: ")
        # self.e5.setStyleSheet("color: rgb(250,50,50); background-color: rgb(250,250,250);")
        self.grid_body_upper.addWidget(self.e5, 0, 3)

        ### Grid BODY ###
        # Custom VIEWER
        self.grid_body.addWidget(self.viewer, 0, 0)

        ### Grid BODY LOWER ###
        # Static Text Field
        self.e7 = QLineEdit()
        self.e7.setMaximumWidth(250)
        self.e7.setAlignment(Qt.AlignRight)
        self.e7.setReadOnly(True)
        self.e7.setText("Select section quality:")
        self.grid_body_lower.addWidget(self.e7, 0, 1)
        # Dropbown Menu (ComboBox) for selecting Stack
        self.dd = QComboBox()
        quality_options = ['unusable', 'blurry', 'good']
        self.dd.addItems(quality_options)
        self.grid_body_lower.addWidget(self.dd, 0, 2)
        # Button Text Field
        self.b_remove = QPushButton("Remove section")
        self.b_remove.setDefault(True)
        self.b_remove.setEnabled(True)
        self.b_remove.setStyleSheet("color: rgb(0,0,0); background-color: #C91B1B;")
        self.grid_body_lower.addWidget(self.b_remove, 2, 1)
        #self.grid_body_lower.addWidget(self.b_addPlaceholder, 2, 2)
        # Button Text Field
        self.b_left = QPushButton("<--   Move Section Left   <--")
        self.b_left.setDefault(True)
        self.b_left.setEnabled(True)
        self.b_left.setStyleSheet("color: rgb(0,0,0); background-color: rgb(200,250,250);")
        self.grid_body_lower.addWidget(self.b_left, 0, 5)
        # Button Text Field
        self.b_right = QPushButton("-->   Move Section Right   -->")
        self.b_right.setDefault(True)
        self.b_right.setEnabled(True)
        self.b_right.setStyleSheet("color: rgb(0,0,0); background-color: rgb(200,250,250);")
        self.grid_body_lower.addWidget(self.b_right, 0, 6)
        # Button Text Field
        self.b_done = QPushButton("Finished")
        self.b_done.setDefault(True)
        self.b_done.setEnabled(True)
        self.b_done.setStyleSheet("color: rgb(0,0,0); background-color: #dfbb19;")
        self.grid_body_lower.addWidget(self.b_done, 2, 6)

        # Grid stretching
        # self.grid_body_upper.setColumnStretch(0, 2)
        self.grid_body_upper.setColumnStretch(2, 2)
        # self.grid_body_lower.setColumnStretch(3, 1)

        ### SUPERGRID ###
        self.supergrid = QGridLayout()
        self.supergrid.addLayout(self.grid_top, 0, 0)
        self.supergrid.addLayout(self.grid_body_upper, 1, 0)
        self.supergrid.addLayout(self.grid_body, 2, 0)
        self.supergrid.addLayout(self.grid_body_lower, 7, 0)

        # Set layout and window title
        self.setLayout(self.supergrid)
        self.setWindowTitle("Q")

    def set_curr_section(self, section_index=-1):
        """
        Sets the current section to the section passed in.
        Will automatically update curr_section, prev_section, and next_section.
        Updates the header fields and loads the current section image.
        """
        if section_index == -1:
            section_index = self.curr_section_index

        # Update curr, prev, and next section
        self.curr_section_index = section_index
        self.curr_section = self.valid_sections[self.valid_section_keys[self.curr_section_index]]['destination']

        # Update the section and filename at the top
        label = self.valid_sections[self.valid_section_keys[self.curr_section_index]]['source']
        self.e4.setText(label)
        self.e5.setText(str(self.curr_section))

        # Update the quality selection in the bottom left
        curr_fn = self.valid_sections[self.valid_section_keys[self.curr_section_index]]
        text = curr_fn['quality']
        index = self.dd.findText(text, Qt.MatchFixedString)
        if index >= 0:
            self.dd.setCurrentIndex(index)

        # Get filepath of "curr_section" and set it as viewer's photo
        img_fp = os.path.join(self.fileLocationManager.thumbnail_prep, self.curr_section)
        self.viewer.set_photo(QPixmap(img_fp))

    def get_valid_section_index(self, section_index):
        if section_index >= len(self.valid_sections):
            return 0
        elif section_index < 0:
            return len(self.valid_sections) - 1
        else:
            return section_index

    def click_button(self, button):
        if button in [self.b_left, self.b_right, self.b_remove]:
            section_number = self.valid_sections[self.valid_section_keys[self.curr_section_index]]['section_number']

            if button == self.b_left:
                self.sqlController.move_section(self.stack, section_number, -1)
            elif button == self.b_right:
                self.sqlController.move_section(self.stack, section_number, 1)
            elif button == self.b_remove:
                result = self.message_box(
                    'Are you sure you want to totally remove this section from this brain?\n\n' +
                    'Warning: The image will be marked as irrelevant to the current brain!',
                    True
                )

                # The answer is Yes
                if result == 2:
                    # Remove the current section from "self.valid_sections
                    self.sqlController.inactivate_section(self.stack, section_number)
                    self.valid_sections = self.sqlController.get_valid_sections(self.stack)
                    self.valid_section_keys = sorted(list(self.valid_sections))

                    if self.curr_section_index == 0:
                        self.curr_section_index = len(self.valid_section_keys) - 1
                    else:
                        self.curr_section_index = self.curr_section_index - 1
            else:
                pass

            # Update the Viewer info and displayed image
            self.valid_sections = self.sqlController.get_valid_sections(self.stack)
            self.valid_section_keys = sorted(list(self.valid_sections))
            self.set_curr_section(self.curr_section_index)
        elif button == self.b_help:
            self.message_box(
                'This GUI is used to align slices to each other. The shortcut commands are as follows: \n\n' +
                '-  `[`: Go back one section. \n' +
                '-  `]`: Go forward one section. \n\n' +
                'Use the buttons on the bottom panel to move',
                False
            )
        elif button == self.dd:
            # Get dropdown selection
            dropdown_selection = self.dd.currentText()
            curr_section = self.valid_sections[self.valid_section_keys[self.curr_section_index]]
            curr_section['quality'] = dropdown_selection
        elif button == self.b_done:
            self.sqlController.set_step_completed_in_progress_ini(self.stack, '1-4_setup_sorted_filenames')
            self.sqlController.save_valid_sections(self.valid_sections)
            sys.exit(app.exec_())

    def message_box(self, text, is_warn):
        msg_box = QMessageBox()
        msg_box.setText(text)

        if is_warn:
            msg_box.addButton(QPushButton('Cancel'), QMessageBox.RejectRole)
            msg_box.addButton(QPushButton('No'), QMessageBox.NoRole)
            msg_box.addButton(QPushButton('Yes'), QMessageBox.YesRole)

        return msg_box.exec_()

    def keyPressEvent(self, event):
        try:
            key = event.key()
        except AttributeError:
            key = event

        if key == 91:  # [
            index = self.get_valid_section_index(self.curr_section_index - 1)
            self.set_curr_section(index)
        elif key == 93:  # ]
            index = self.get_valid_section_index(self.curr_section_index + 1)
            self.set_curr_section(index)
        else:
            print(key)

    def closeEvent(self, event):
        sys.exit(app.exec_())
        # close_main_gui( ex, reopen=True )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='GUI for sorting filenames')
    parser.add_argument("stack", type=str, help="stack name")
    args = parser.parse_args()
    stack = args.stack

    app = QApplication(sys.argv)
    ex = GUISortedFilenames(stack)
    ex.keyPressEvent(91)
    ex.show()
    sys.exit(app.exec_())
