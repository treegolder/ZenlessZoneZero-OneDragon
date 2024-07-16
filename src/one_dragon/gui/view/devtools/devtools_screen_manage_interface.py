import os
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget, QFileDialog, QTableWidgetItem
from qfluentwidgets import FluentIcon, PushButton, TableWidget, ToolButton, ComboBox

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.context_base import OneDragonContext
from one_dragon.base.screen.screen_area import ScreenArea
from one_dragon.base.screen.screen_info import ScreenInfo
from one_dragon.gui.component.column_widget import ColumnWidget
from one_dragon.gui.component.cv2_image import Cv2Image
from one_dragon.gui.component.interface.vertical_scroll_interface import VerticalScrollInterface
from one_dragon.gui.component.label.click_image_label import ClickImageLabel, ImageScaleEnum
from one_dragon.gui.component.row_widget import RowWidget
from one_dragon.gui.component.setting_card.check_box_setting_card import CheckBoxSettingCard
from one_dragon.gui.component.setting_card.combo_box_setting_card import ComboBoxSettingCard
from one_dragon.gui.component.setting_card.text_setting_card import TextSettingCard
from one_dragon.utils import os_utils, cv2_utils
from one_dragon.utils.i18_utils import gt
from one_dragon.utils.log_utils import log


class ScreenInfoWorker(QObject):

    signal = Signal()


class DevtoolsScreenManageInterface(VerticalScrollInterface):

    def __init__(self, ctx: OneDragonContext, parent=None):
        content_widget = RowWidget()

        VerticalScrollInterface.__init__(
            self,
            ctx=ctx,
            content_widget=content_widget,
            object_name='devtools_screen_manage_interface',
            parent=parent,
            nav_text_cn='画面管理'
        )

        content_widget.add_widget(self._init_left_part())
        content_widget.add_widget(self._init_right_part())

        self.chosen_screen: ScreenInfo = None

        self._whole_update = ScreenInfoWorker()
        self._whole_update.signal.connect(self._update_display_by_screen)

        self._image_update = ScreenInfoWorker()
        self._image_update.signal.connect(self._update_image_display)

        self._area_table_update = ScreenInfoWorker()
        self._area_table_update.signal.connect(self._update_area_table_display)

        self._existed_yml_update = ScreenInfoWorker()
        self._existed_yml_update.signal.connect(self._update_existed_yml_options)

    def _init_left_part(self) -> QWidget:
        widget = ColumnWidget()

        btn_row = RowWidget()
        widget.add_widget(btn_row)

        self.existed_yml_btn = ComboBox()
        self.existed_yml_btn.setPlaceholderText(gt('选择已有', 'ui'))
        self._update_existed_yml_options()
        btn_row.add_widget(self.existed_yml_btn)

        self.create_btn = PushButton(text=gt('新建', 'ui'))
        self.create_btn.clicked.connect(self._on_create_clicked)
        btn_row.add_widget(self.create_btn)

        self.save_btn = PushButton(text=gt('保存', 'ui'))
        self.save_btn.clicked.connect(self._on_save_clicked)
        btn_row.add_widget(self.save_btn)

        self.delete_btn = PushButton(text=gt('删除', 'ui'))
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        btn_row.add_widget(self.delete_btn)

        self.cancel_btn = PushButton(text=gt('取消', 'ui'))
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        btn_row.add_widget(self.cancel_btn)

        btn_row.add_stretch(1)

        self.choose_image_btn = PushButton(text=gt('选择图片', 'ui'))
        self.choose_image_btn.clicked.connect(self.choose_existed_image)
        widget.add_widget(self.choose_image_btn)

        self.screen_id_opt = TextSettingCard(icon=FluentIcon.HOME, title='画面ID')
        self.screen_id_opt.value_changed.connect(self._on_screen_id_changed)
        widget.add_widget(self.screen_id_opt)

        self.screen_name_opt = TextSettingCard(icon=FluentIcon.HOME, title='画面名称')
        self.screen_name_opt.value_changed.connect(self._on_screen_name_changed)
        widget.add_widget(self.screen_name_opt)

        self.pc_alt_opt = CheckBoxSettingCard(icon=FluentIcon.MOVE, title='PC点击需alt')
        self.pc_alt_opt.value_changed.connect(self._on_pc_alt_changed)
        widget.add_widget(self.pc_alt_opt)

        self.area_table = TableWidget()
        self.area_table.setMinimumWidth(700)
        self.area_table.setMinimumHeight(420)
        self.area_table.setBorderVisible(True)
        self.area_table.setBorderRadius(8)
        self.area_table.setWordWrap(True)
        self.area_table.setColumnCount(7)
        self.area_table.verticalHeader().hide()
        self.area_table.setHorizontalHeaderLabels([
            gt('操作', 'ui'),
            gt('区域名称', 'ui'),
            gt('位置', 'ui'),
            gt('文本', 'ui'),
            gt('阈值', 'ui'),
            gt('模板', 'ui'),
            gt('阈值', 'ui')
        ])
        self.area_table.setColumnWidth(0, 40)  # 操作
        self.area_table.setColumnWidth(2, 200)  # 位置
        self.area_table.setColumnWidth(4, 70)  # 文本阈值
        self.area_table.setColumnWidth(6, 70)  # 模板阈值
        widget.add_widget(self.area_table)

        widget.add_stretch(1)
        return widget

    def _update_existed_yml_options(self) -> None:
        """
        更新已有的yml选项
        :return:
        """
        try:
            # 更新之前 先取消原来的监听 防止触发事件
            self.existed_yml_btn.currentTextChanged.disconnect(self._on_choose_existed_yml)
        except Exception:
            pass
        self.existed_yml_btn.clear()
        self.existed_yml_btn.addItems(
            [i.screen_name for i in self.ctx.screen_loader._screen_info_list]
        )
        self.existed_yml_btn.setCurrentIndex(-1)
        self.existed_yml_btn.setPlaceholderText(gt('选择已有', 'ui'))
        self.existed_yml_btn.currentTextChanged.connect(self._on_choose_existed_yml)

    def _init_right_part(self) -> QWidget:
        widget = ColumnWidget()

        self.image_display_size_opt = ComboBoxSettingCard(
            icon=FluentIcon.ZOOM_IN, title='图片显示大小',
            options=ImageScaleEnum
        )
        self.image_display_size_opt.setValue(0.5)
        self.image_display_size_opt.value_changed.connect(self._update_image_display)
        widget.add_widget(self.image_display_size_opt)

        self.image_click_pos_opt = TextSettingCard(icon=FluentIcon.MOVE, title='鼠标选择区域')
        widget.add_widget(self.image_click_pos_opt)

        self.image_label = ClickImageLabel()
        self.image_label.drag_released.connect(self._on_image_drag_released)
        widget.add_widget(self.image_label)

        widget.add_stretch(1)

        return widget

    def init_on_shown(self) -> None:
        """
        子界面显示时 进行初始化
        :return:
        """
        self._update_display_by_screen()

    def _update_display_by_screen(self) -> None:
        """
        根据画面图片，统一更新界面的显示
        :return:
        """
        chosen = self.chosen_screen is not None

        self.existed_yml_btn.setDisabled(chosen)
        self.create_btn.setDisabled(chosen)
        self.save_btn.setDisabled(not chosen)
        self.delete_btn.setDisabled(not chosen)
        self.cancel_btn.setDisabled(not chosen)

        self.choose_image_btn.setDisabled(not chosen)
        self.screen_id_opt.setDisabled(not chosen)
        self.screen_name_opt.setDisabled(not chosen)
        self.pc_alt_opt.setDisabled(not chosen)

        if not chosen:  # 清除一些值
            self.screen_id_opt.setValue('')
            self.screen_name_opt.setValue('')
            self.pc_alt_opt.setValue(False)
        else:
            self.screen_id_opt.setValue(self.chosen_screen.screen_id)
            self.screen_name_opt.setValue(self.chosen_screen.screen_name)
            self.pc_alt_opt.setValue(self.chosen_screen.pc_alt)

        self._update_image_display()
        self._update_area_table_display()

    def _update_area_table_display(self):
        """
        更新区域表格的显示
        :return:
        """
        try:
            # 更新之前 先取消原来的监听 防止触发事件
            self.area_table.cellChanged.disconnect(self._on_area_table_cell_changed)
        except Exception:
            pass
        area_list = [] if self.chosen_screen is None else self.chosen_screen.area_list
        area_cnt = len(area_list)
        self.area_table.setRowCount(area_cnt + 1)

        for idx in range(area_cnt):
            area_item = area_list[idx]
            del_btn = ToolButton(FluentIcon.DELETE)
            del_btn.clicked.connect(self._on_row_delete_clicked)

            self.area_table.setCellWidget(idx, 0, del_btn)
            self.area_table.setItem(idx, 1, QTableWidgetItem(area_item.area_name))
            self.area_table.setItem(idx, 2, QTableWidgetItem(str(area_item.pc_rect)))
            self.area_table.setItem(idx, 3, QTableWidgetItem(area_item.text))
            self.area_table.setItem(idx, 4, QTableWidgetItem(str(area_item.lcs_percent)))
            self.area_table.setItem(idx, 5, QTableWidgetItem(area_item.template_id_display_text))
            self.area_table.setItem(idx, 6, QTableWidgetItem(str(area_item.template_match_threshold)))

        add_btn = ToolButton(FluentIcon.ADD)
        add_btn.clicked.connect(self._on_area_add_clicked)
        self.area_table.setCellWidget(area_cnt, 0, add_btn)
        self.area_table.setItem(area_cnt, 1, QTableWidgetItem(''))
        self.area_table.setItem(area_cnt, 2, QTableWidgetItem(''))
        self.area_table.setItem(area_cnt, 3, QTableWidgetItem(''))
        self.area_table.setItem(area_cnt, 4, QTableWidgetItem(''))
        self.area_table.setItem(area_cnt, 5, QTableWidgetItem(''))
        self.area_table.setItem(area_cnt, 6, QTableWidgetItem(''))

        self.area_table.cellChanged.connect(self._on_area_table_cell_changed)

    def _update_image_display(self):
        """
        更新图片显示
        :return:
        """
        image_to_show = None if self.chosen_screen is None else self.chosen_screen.get_image_to_show()
        if image_to_show is not None:
            image = Cv2Image(image_to_show)
            self.image_label.setImage(image)
            size_value: float = self.image_display_size_opt.getValue()
            if size_value is None:
                display_width = image.width()
                display_height = image.height()
            else:
                display_width = int(image.width() * size_value)
                display_height = int(image.height() * size_value)
            self.image_label.setFixedSize(display_width, display_height)
        else:
            self.image_label.setImage(None)

    def _on_choose_existed_yml(self, screen_name: str):
        """
        选择了已有的yml
        :param screen_name:
        :return:
        """
        for screen_info in self.ctx.screen_loader._screen_info_list:
            if screen_info.screen_name == screen_name:
                self.chosen_screen = ScreenInfo(screen_id=screen_info.screen_id)
                self._whole_update.signal.emit()
                break

    def _on_create_clicked(self):
        """
        创建一个新的
        :return:
        """
        if self.chosen_screen is not None:
            return

        self.chosen_screen = ScreenInfo(create_new=True)
        self._whole_update.signal.emit()

    def _on_save_clicked(self) -> None:
        """
        保存
        :return:
        """
        if self.chosen_screen is None:
            return

        self.chosen_screen.save()
        self.ctx.screen_loader.load_all()
        self._existed_yml_update.signal.emit()

    def _on_delete_clicked(self) -> None:
        """
        删除
        :return:
        """
        if self.chosen_screen is None:
            return
        self.chosen_screen.delete()
        self.chosen_screen = None
        self._whole_update.signal.emit()
        self._existed_yml_update.signal.emit()

    def _on_cancel_clicked(self) -> None:
        """
        取消编辑
        :return:
        """
        self.chosen_screen = None
        self.existed_yml_btn.setCurrentIndex(-1)
        self._whole_update.signal.emit()

    def choose_existed_image(self) -> None:
        """
        选择已有的环图片
        :return:
        """
        default_dir = os_utils.get_path_under_work_dir('.debug', 'images')
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            gt('选择图片', 'ui'),
            dir=default_dir,
            filter="PNG (*.png)",
        )
        if file_path is not None and file_path.endswith('.png'):
            fix_file_path = os.path.normpath(file_path)
            log.info('选择路径 %s', fix_file_path)
            self._on_image_chosen(fix_file_path)

    def _on_image_chosen(self, image_file_path: str) -> None:
        """
        选择图片之后的回调
        :param image_file_path:
        :return:
        """
        if self.chosen_screen is None:
            return

        self.chosen_screen.screen_image = cv2_utils.read_image(image_file_path)
        self._image_update.signal.emit()

    def _on_screen_id_changed(self, value: str) -> None:
        if self.chosen_screen is None:
            return

        self.chosen_screen.screen_id = value

    def _on_screen_name_changed(self, value: str) -> None:
        if self.chosen_screen is None:
            return

        self.chosen_screen.screen_name = value

    def _on_pc_alt_changed(self, value: bool) -> None:
        if self.chosen_screen is None:
            return

        self.chosen_screen.pc_alt = value

    def _on_area_add_clicked(self) -> None:
        """
        新增一个区域
        :return:
        """
        if self.chosen_screen is None:
            return

        self.chosen_screen.area_list.append(ScreenArea())
        self._area_table_update.signal.emit()

    def _on_row_delete_clicked(self):
        """
        删除一行
        :return:
        """
        if self.chosen_screen is None:
            return

        button_idx = self.sender()
        if button_idx is not None:
            row_idx = self.area_table.indexAt(button_idx.pos()).row()
            self.chosen_screen.remove_area_by_idx(row_idx)
            self.area_table.removeRow(row_idx)
            self._image_update.signal.emit()

    def _on_area_table_cell_changed(self, row: int, column: int) -> None:
        """
        表格内容改变
        :param row:
        :param column:
        :return:
        """
        if self.chosen_screen is None:
            return
        if row < 0 or row >= len(self.chosen_screen.area_list):
            return
        area_item = self.chosen_screen.area_list[row]
        text = self.area_table.item(row, column).text().strip()
        if column == 1:
            area_item.area_name = text
        elif column == 2:
            num_list = [int(i) for i in text[1:-1].split(',')]
            while len(num_list) < 4:
                num_list.append(0)
            area_item.pc_rect = Rect(num_list[0], num_list[1], num_list[2], num_list[3])
            self._image_update.signal.emit()
        elif column == 3:
            area_item.text = text
        elif column == 4:
            area_item.lcs_percent = float(text) if len(text) > 0 else 0.5
        elif column == 5:
            if len(text) == 0:
                area_item.template_sub_dir = ''
                area_item.template_id = ''
            else:
                template_list = text.split(',')
                if len(template_list) > 1:
                    area_item.template_sub_dir = template_list[0]
                    area_item.template_id = template_list[1]
                else:
                    area_item.template_sub_dir = ''
                    area_item.template_id = template_list[0]
        elif column == 6:
            area_item.template_match_threshold = float(text) if len(text) > 0 else 0.7

    def _on_image_drag_released(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """
        图片上拖拽区域后 显示坐标
        :return:
        """
        if self.chosen_screen is None or self.chosen_screen.screen_image is None:
            return

        display_width = self.image_label.width()
        display_height = self.image_label.height()

        image_width = self.chosen_screen.screen_image.shape[1]
        image_height = self.chosen_screen.screen_image.shape[0]

        real_x1 = int(x1 * image_width / display_width)
        real_y1 = int(y1 * image_height / display_height)
        real_x2 = int(x2 * image_width / display_width)
        real_y2 = int(y2 * image_height / display_height)

        self.image_click_pos_opt.setValue(f'{real_x1}, {real_y1}, {real_x2}, {real_y2}')