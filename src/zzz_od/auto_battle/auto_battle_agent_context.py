from concurrent.futures import ThreadPoolExecutor, Future

import threading
from cv2.typing import MatLike
from typing import Optional, List, Union

from one_dragon.base.conditional_operation.conditional_operator import ConditionalOperator
from one_dragon.base.conditional_operation.state_recorder import StateRecord, StateRecorder
from one_dragon.base.screen.screen_area import ScreenArea
from one_dragon.utils import cv2_utils, cal_utils
from one_dragon.utils.log_utils import log
from zzz_od.auto_battle.agent_state import agent_state_checker
from zzz_od.auto_battle.auto_battle_state import BattleStateEnum
from zzz_od.context.zzz_context import ZContext
from zzz_od.game_data.agent import Agent, AgentEnum, AgentStateCheckWay, CommonAgentStateEnum, AgentStateDef

_battle_agent_context_executor = ThreadPoolExecutor(thread_name_prefix='od_battle_agent_context', max_workers=16)


class AgentInfo:

    def __init__(self, agent: Optional[Agent], energy: int = 0):
        self.agent: Agent = agent
        self.energy: int = energy  # 能量


class TeamInfo:

    def __init__(self, agent_names: Optional[List[str]] = None):
        self.agent_list: List[AgentInfo] = []

        self.should_check_all_agents: bool = agent_names is None  # 是否应该检查所有角色
        self.check_agent_same_times: int = 0  # 识别角色的相同次数
        self.check_agent_diff_times: int = 0  # 识别角色的不同次数
        self.update_agent_lock = threading.Lock()
        self.agent_update_time: float = 0  # 识别角色的更新时间

        if agent_names is not None:
            for agent_name in agent_names:
                for agent_enum in AgentEnum:
                    if agent_name == agent_enum.value.agent_name:
                        self.agent_list.append(AgentInfo(agent_enum.value))
                        break

    def update_agent_list(self,
                          current_agent_list: List[Agent],
                          energy_list: List[int],
                          update_time: float,) -> bool:
        """
        更新角色列表
        :param current_agent_list: 新的角色列表
        :param energy_list: 能量列表
        :param update_time: 更新时间
        :return: 本次是否更新了
        """
        with self.update_agent_lock:

            if self.should_check_all_agents:
                if self.is_same_agent_list(current_agent_list):
                    self.check_agent_same_times += 1
                    if self.check_agent_same_times >= 5:  # 连续5次一致时 就不验证了
                        self.should_check_all_agents = False
                        log.debug("停止识别新角色")
                else:
                    self.check_agent_same_times = 0
            else:
                if not self.is_same_agent_list(current_agent_list):
                    self.check_agent_diff_times += 1
                    if self.check_agent_diff_times >= 250:  # 0.02秒1次 大概5s不一致就重新识别 除了减员情况外基本不可能出现
                        self.should_check_all_agents = True
                        log.debug("重新识别新角色")
                else:
                    self.check_agent_diff_times = 0

            if not self.should_check_all_agents and not self.is_same_agent_list(current_agent_list):
                # 如果已经确定角色列表了 那识别出来的应该是一样的
                # 不一样的话 就不更新了
                return False

            if update_time < self.agent_update_time:  # 可能是过时的截图 这时候不更新
                return False
            self.agent_update_time = update_time

            log.debug('当前角色列表 %s', [
                i.agent.agent_name if i.agent is not None else 'none'
                for i in self.agent_list
            ])

            self.agent_list = []
            for i in range(len(current_agent_list)):
                energy = energy_list[i] if i < len(energy_list) else 0
                self.agent_list.append(AgentInfo(current_agent_list[i], energy))

            log.debug('更新后角色列表 %s', [
                i.agent.agent_name if i.agent is not None else 'none'
                for i in self.agent_list
            ])

            return True

    def is_same_agent_list(self, current_agent_list: List[Agent]) -> bool:
        """
        是否跟原来的角色列表一致 忽略顺序
        :param current_agent_list:
        :return:
        """
        if self.agent_list is None or current_agent_list is None:
            return False
        if len(self.agent_list) != len(current_agent_list):
            return False
        old_agent_ids = [i.agent.agent_id for i in self.agent_list if i.agent is not None]
        new_agent_ids = [i.agent_id for i in current_agent_list if i is not None]
        if len(old_agent_ids) != len(new_agent_ids):
            return False

        for old_agent_id in old_agent_ids:
            if old_agent_id not in new_agent_ids:
                return False

        return True

    def switch_next_agent(self, update_time: float) -> bool:
        """
        切换到下一个代理人
        :param update_time: 更新时间
        :return: 是否更新了代理人列表
        """
        with self.update_agent_lock:
            if update_time < self.agent_update_time:
                return False

            if self.agent_list is None or len(self.agent_list) == 0:
                return False
            self.agent_update_time = update_time

            not_none_agent_list = []
            none_cnt: int = 0
            for i in self.agent_list:
                if i.agent is None:
                    none_cnt += 1
                else:
                    not_none_agent_list.append(i)

            next_agent_list = []
            if len(not_none_agent_list) > 0:
                for i in range(1, len(not_none_agent_list)):
                    next_agent_list.append(not_none_agent_list[i])
                next_agent_list.append(not_none_agent_list[0])

            for i in range(none_cnt):
                next_agent_list.append(AgentInfo(None, 0))

            self.agent_list = next_agent_list
            return True

    def switch_prev_agent(self, update_time: float) -> bool:
        """
        切换到上一个代理人
        :param update_time: 更新时间
        :return: 是否更新了代理人列表
        """
        with self.update_agent_lock:
            if update_time < self.agent_update_time:
                return False

            if self.agent_list is None or len(self.agent_list) == 0:
                return False
            self.agent_update_time = update_time

            not_none_agent_list = []
            none_cnt: int = 0
            for i in self.agent_list:
                if i.agent is None:
                    none_cnt += 1
                else:
                    not_none_agent_list.append(i)

            next_agent_list = []
            if len(not_none_agent_list) > 0:
                next_agent_list.append(not_none_agent_list[-1])
                for i in range(0, len(not_none_agent_list)-1):
                    next_agent_list.append(not_none_agent_list[i])

            for i in range(none_cnt):
                next_agent_list.append(AgentInfo(None, 0))
            self.agent_list = next_agent_list
            return True

    def get_agent_pos(self, agent: Agent) -> int:
        """
        获取指定代理人在队伍当前的位置
        :return: 如果存在就返回1~3 不存在就返回0
        """
        for i in range(len(self.agent_list)):
            if self.agent_list[i].agent is None:
                continue
            if self.agent_list[i].agent.agent_id == agent.agent_id:
                return i + 1
        return 0


class AutoBattleAgentContext:

    def __init__(self, ctx: ZContext):
        self.ctx: ZContext = ctx
        self.auto_op: ConditionalOperator = ConditionalOperator('', '', is_mock=True)
        self.team_info: TeamInfo = TeamInfo()

        # 识别锁 保证每种类型只有1实例在进行识别
        self._check_agent_lock = threading.Lock()

    def init_battle_agent_context(
            self,
            auto_op: ConditionalOperator,
            agent_names: Optional[List[str]] = None,
            to_check_state_list: Optional[List[str]] = None,
            allow_ultimate_list: Optional[List[dict[str, str]]] = None,
            check_agent_interval: Union[float, List[float]] = 0,) -> None:
        """
        自动战斗前的初始化
        :return:
        """
        self.auto_op: ConditionalOperator = auto_op
        self.team_info: TeamInfo = TeamInfo(agent_names)
        self._allow_ultimate_list: List[dict[str, str]] = allow_ultimate_list  # 允许使用终结技的角色

        # 识别区域 先读取出来 不要每次用的时候再读取
        self.area_agent_3_1: ScreenArea = self.ctx.screen_loader.get_area('战斗画面', '头像-3-1')
        self.area_agent_3_2: ScreenArea = self.ctx.screen_loader.get_area('战斗画面', '头像-3-2')
        self.area_agent_3_3: ScreenArea = self.ctx.screen_loader.get_area('战斗画面', '头像-3-3')
        self.area_agent_2_2: ScreenArea = self.ctx.screen_loader.get_area('战斗画面', '头像-2-2')

        # 识别间隔
        self._check_agent_interval = check_agent_interval

        # 上一次识别的时间
        self._last_check_agent_time: float = 0

        # 初始化需要检测的状态
        for agent_enum in AgentEnum:
            agent = agent_enum.value
            if agent.state_list is None:
                continue
            for state in agent.state_list:
                if to_check_state_list is not None:
                    state.should_check_in_battle = state.state_name in to_check_state_list
                else:
                    state.should_check_in_battle = True

        for state_enum in CommonAgentStateEnum:
            state = state_enum.value
            if to_check_state_list is not None:
                state.should_check_in_battle = state.state_name in to_check_state_list
            else:
                state.should_check_in_battle = True

    def get_possible_agent_list(self) -> Optional[List[Agent]]:
        """
        获取用于匹配的候选角色列表
        """
        all: bool = False
        if self.team_info.should_check_all_agents:
            all = True
        elif self.team_info.agent_list is None or len(self.team_info.agent_list) == 0:
            all = True
        else:
            for i in self.team_info.agent_list:
                if i.agent is None:
                    all = True
                    break
        if all:
            return [agent_enum.value for agent_enum in AgentEnum]
        else:
            return [i.agent for i in self.team_info.agent_list if i.agent is not None]

    def check_agent_related(self, screen: MatLike, screenshot_time: float) -> None:
        """
        判断角色相关内容 并发送事件
        :return:
        """
        if not self._check_agent_lock.acquire(blocking=False):
            return

        try:
            if screenshot_time - self._last_check_agent_time < cal_utils.random_in_range(self._check_agent_interval):
                # 还没有达到识别间隔
                return
            self._last_check_agent_time = screenshot_time

            screen_agent_list = self._check_agent_in_parallel(screen)
            energy_state_list = self._check_energy_in_parallel(screen, screenshot_time, screen_agent_list)

            front_state_list = self._check_front_agent_state(screen, screenshot_time, screen_agent_list)
            life_state_list = self._check_life_deduction(screen, screenshot_time, screen_agent_list)

            update_state_record_list = []

            # 尝试更新代理人列表 成功的话 更新状态记录
            if self.team_info.update_agent_list(
                    screen_agent_list,
                    [(i.value if i is not None else 0) for i in energy_state_list],
                    screenshot_time):

                for i in self._get_agent_state_records(screenshot_time):
                    update_state_record_list.append(i)

            for i in front_state_list:
                update_state_record_list.append(i)
            for i in life_state_list:
                update_state_record_list.append(i)

            self.auto_op.batch_update_states(update_state_record_list)
        except Exception:
            log.error('识别画面角色失败', exc_info=True)
        finally:
            self._check_agent_lock.release()

    def _check_agent_in_parallel(self, screen: MatLike) -> List[Agent]:
        """
        并发识别角色
        :return:
        """
        area_img = [
            cv2_utils.crop_image_only(screen, self.area_agent_3_1.rect),
            cv2_utils.crop_image_only(screen, self.area_agent_3_2.rect),
            cv2_utils.crop_image_only(screen, self.area_agent_3_3.rect),
            cv2_utils.crop_image_only(screen, self.area_agent_2_2.rect)
        ]

        possible_agents = self.get_possible_agent_list()

        result_agent_list: List[Optional[Agent]] = []
        future_list: List[Optional[Future]] = []
        should_check: List[bool] = [True, False, False, False]

        if not self.team_info.should_check_all_agents:
            if len(self.team_info.agent_list) == 3:
                should_check[1] = True
                should_check[2] = True
            elif len(self.team_info.agent_list) == 2:
                should_check[3] = True
        else:
            for i in range(4):
                should_check[i] = True

        for i in range(4):
            if should_check[i]:
                future_list.append(_battle_agent_context_executor.submit(self._match_agent_in, area_img[i], i == 0, possible_agents))
            else:
                future_list.append(None)

        for future in future_list:
            if future is None:
                result_agent_list.append(None)
                continue
            try:
                result = future.result()
                result_agent_list.append(result)
            except Exception:
                log.error('识别角色头像失败', exc_info=True)
                result_agent_list.append(None)

        if result_agent_list[1] is not None and result_agent_list[2] is not None:  # 3人
            current_agent_list = result_agent_list[:3]
        elif result_agent_list[3] is not None:  # 2人
            current_agent_list = [result_agent_list[0], result_agent_list[3]]
        else:  # 1人
            current_agent_list = [result_agent_list[0]]

        return current_agent_list

    def _match_agent_in(self, img: MatLike, is_front: bool,
                        possible_agents: Optional[List[Agent]] = None) -> Optional[Agent]:
        """
        在候选列表重匹配角色
        :return:
        """
        prefix = 'avatar_1_' if is_front else 'avatar_2_'
        for agent in possible_agents:
            mrl = self.ctx.tm.match_template(img, 'battle', prefix + agent.agent_id, threshold=0.8)
            if mrl.max is not None:
                return agent

        return None

    def _check_front_agent_state(self, screen: MatLike, screenshot_time: float, screen_agent_list: List[Agent]) -> List[StateRecord]:
        """
        识别前台角色的状态
        :param screen: 游戏画面
        :param screenshot_time: 截图时间
        :param screen_agent_list: 当前画面前台角色
        :return:
        """
        if screen_agent_list is None or len(screen_agent_list) == 0 or screen_agent_list[0] is None:
            return []
        front_agent: Agent = screen_agent_list[0]
        if front_agent.state_list is None:
            return []

        return self._check_agent_state_in_parallel(screen, screenshot_time, front_agent.state_list)

    def _check_agent_state_in_parallel(self, screen: MatLike, screenshot_time: float, agent_state_list: List[AgentStateDef]) -> List[StateRecord]:
        """
        并行识别多个角色状态
        :param screen: 游戏画面
        :param screenshot_time: 截图时间
        :param agent_state_list: 需要识别的状态列表
        :return:
        """
        future_list: List[Future] = []
        for state in agent_state_list:
            if not state.should_check_in_battle:
                continue
            future_list.append(_battle_agent_context_executor.submit(self._check_agent_state, screen, screenshot_time, state))

        result_list: List[Optional[StateRecord]] = []
        for future in future_list:
            try:
                record = future.result()
                if record is not None:
                    result_list.append(record)
            except Exception:
                log.error('识别角色状态失败', exc_info=True)

        return result_list

    def _check_agent_state(self, screen: MatLike, screenshot_time: float, state: AgentStateDef) -> Optional[StateRecord]:
        """
        识别一个角色状态
        :param screen:
        :param screenshot_time:
        :return:
        """
        value: int = -1
        if state.check_way == AgentStateCheckWay.COLOR_RANGE_CONNECT:
            value = agent_state_checker.check_cnt_by_color_range(self.ctx, screen, state)
        if state.check_way == AgentStateCheckWay.COLOR_RANGE_EXIST:
            value = agent_state_checker.check_exist_by_color_range(self.ctx, screen, state)
            value = 1 if value else 0
        elif state.check_way == AgentStateCheckWay.BACKGROUND_GRAY_RANGE_LENGTH:
            value = agent_state_checker.check_length_by_background_gray(self.ctx, screen, state)
        elif state.check_way == AgentStateCheckWay.FOREGROUND_GRAY_RANGE_LENGTH:
            value = agent_state_checker.check_length_by_foreground_gray(self.ctx, screen, state)
        elif state.check_way == AgentStateCheckWay.FOREGROUND_COLOR_RANGE_LENGTH:
            value = agent_state_checker.check_length_by_foreground_color(self.ctx, screen, state)

        if value > -1 and value >= state.min_value_trigger_state:
            return StateRecord(state.state_name, screenshot_time, value)

    def _check_energy_in_parallel(self, screen: MatLike, screenshot_time: float, screen_agent_list: List[Agent]) -> List[StateRecord]:
        """
        识别角色能量
        :param screen:
        :param screenshot_time:
        :param screen_agent_list:
        :return: 各角色的能量值
        """
        if screen_agent_list is None or len(screen_agent_list) == 0:
            return []

        if len(screen_agent_list) == 3:
            state_list = [
                CommonAgentStateEnum.ENERGY_31.value,
                CommonAgentStateEnum.ENERGY_32.value,
                CommonAgentStateEnum.ENERGY_33.value,
            ]
        elif len(screen_agent_list) == 2:
            state_list = [
                CommonAgentStateEnum.ENERGY_21.value,
                CommonAgentStateEnum.ENERGY_22.value,
            ]
        else:
            state_list = [CommonAgentStateEnum.ENERGY_21.value]

        return self._check_agent_state_in_parallel(screen, screenshot_time, state_list)

    def _check_life_deduction(self, screen: MatLike, screenshot_time: float, screen_agent_list: List[Agent]) -> List[StateRecord]:
        """
        识别血量扣减
        :param screen:
        :param screenshot_time:
        :param screen_agent_list:
        :return:
        """
        if screen_agent_list is None or len(screen_agent_list) == 0:
            return []

        state_list = [CommonAgentStateEnum.LIFE_DEDUCTION.value]
        return self._check_agent_state_in_parallel(screen, screenshot_time, state_list)

    def switch_next_agent(self, update_time: float, update_state: bool = True) -> List[StateRecord]:
        """
        代理人列表 切换下一个
        :param update_time: 更新时间
        :param update_state: 是否更新状态
        """
        if self.team_info.switch_next_agent(update_time):
            records = self._get_agent_state_records(update_time)
            records.append(StateRecord(BattleStateEnum.STATUS_SPECIAL_READY.value, is_clear=True))
            if update_state:
                self.auto_op.batch_update_states(records)
            return records
        return []

    def switch_prev_agent(self, update_time: float, update_state: bool = True) -> List[StateRecord]:
        """
        代理人列表 切换上一个
        :param update_time: 更新时间
        :param update_state: 是否更新状态
        """
        if self.team_info.switch_prev_agent(update_time):
            records = self._get_agent_state_records(update_time)
            records.append(StateRecord(BattleStateEnum.STATUS_SPECIAL_READY.value, is_clear=True))
            if update_state:
                self.auto_op.batch_update_states(records)
            return records
        return []

    def switch_quick_assist(self, update_time: float, update_state: bool = True) -> List[StateRecord]:
        """
        切换到快速支援的角色
        :param update_time: 更新时间
        :param update_state: 是否更新状态
        :return:
        """
        # 由于快速支援没法固定是上一个或者下一个 因此要靠快速支援的识别结果来判断是哪个角色
        switch_agent: Optional[Agent] = None
        latest_recorder: Optional[StateRecorder] = None
        for agent_enum in AgentEnum:
            agent = agent_enum.value
            state_name = f'快速支援-{agent.agent_name}'
            state_recorder = self.auto_op.get_state_recorder(state_name)
            if state_recorder is None or state_recorder.last_record_time <= 0:
                continue

            if latest_recorder is None or state_recorder.last_record_time > latest_recorder.last_record_time:
                latest_recorder = state_recorder
                switch_agent = agent

        if switch_agent is None:
            return []

        target_agent_pos = self.team_info.get_agent_pos(switch_agent)
        if target_agent_pos == 2:  # 在下一个
            return self.switch_next_agent(update_time, update_state=update_state)
        elif target_agent_pos == 3:  # 在上一个
            return self.switch_prev_agent(update_time, update_state=update_state)

    def _get_agent_state_records(self, update_time: float) -> List[StateRecord]:
        """
        获取代理人相关的状态
        :param update_time:
        :return:
        """
        state_records = []
        for i in range(len(self.team_info.agent_list)):
            prefix = '前台-' if i == 0 else ('后台-%d-' % i)
            agent_info = self.team_info.agent_list[i]
            agent = agent_info.agent
            if agent is not None:
                state_records.append(StateRecord(prefix + agent.agent_name, update_time))
                state_records.append(StateRecord(prefix + agent.agent_type.value, update_time))

            state_records.append(StateRecord(prefix + '能量', update_time, agent_info.energy))

        if not self.allow_to_use_ultimate():
            state_records.append(StateRecord(BattleStateEnum.STATUS_ULTIMATE_READY.value, is_clear=True))

        return state_records

    def allow_to_use_ultimate(self) -> bool:
        """
        当前角色是否允许使用终结技
        :return:
        """
        if self._allow_ultimate_list is not None:  # 如果配置了终结技
            agent_info_list = self.team_info.agent_list
            if agent_info_list is None or len(agent_info_list) == 0 or agent_info_list[0].agent is None:
                # 未识别到角色时 不允许使用
                return False

            # 前台角色
            front_agent = agent_info_list[0].agent
            for allow_ultimate_item in self._allow_ultimate_list:
                if 'agent_name' in allow_ultimate_item:
                    if allow_ultimate_item.get('agent_name', '') == front_agent.agent_name:
                        return True
                elif 'agent_type' in allow_ultimate_item:
                    if allow_ultimate_item.get('agent_type', '') == front_agent.agent_type.value:
                        return True

            return False

        return True