import abc
import bisect
import random
from copy import deepcopy
from typing import Tuple, Dict

import numpy as np
import torch
import torch.nn as nn

# side, vol, price
ActionType = Tuple[int, float, float]


class ModelOutputWrapper(abc.ABC):

    def __init__(self, model: nn.Module, refresh_model_steps: int = 32):
        self.model_base = model
        self.model = deepcopy(model).to('cpu')
        self.refresh_model_steps = refresh_model_steps
        self._refresh_count = 0

    def refresh_model(self):
        target_params = self.model_base.state_dict()
        self.model.load_state_dict(target_params)

    @staticmethod
    @abc.abstractmethod
    def get_output_shape():
        pass

    @abc.abstractmethod
    def select_action(self, observation, model_input: torch.tensor) -> Tuple[ActionType, torch.tensor, torch.tensor]:
        pass

    @abc.abstractmethod
    def random_action(self, observation, model_input) -> Tuple[ActionType, torch.tensor, torch.tensor]:
        pass


class Action11OutputWrapper(ModelOutputWrapper):
    buy_side = 0
    noop_side = 1
    sell_side = 2
    vol = 1.

    @staticmethod
    def get_output_shape():
        return 11

    def action_id_to_action(self, action_id: int, obs: Dict) -> ActionType:
        # a4 -> a0 -> b0 -> b4 -> noop
        if 0 <= action_id < 5:
            vol = self.vol * (action_id + 1)
            vols = [obs['av0'], obs['av1'], obs['av2'], obs['av3'], obs['av4']]
            prices = [obs['ap0'], obs['ap1'], obs['ap2'], obs['ap3'], obs['ap4']]
            cum_vol = np.cumsum(vols)
            price_id = bisect.bisect_left(cum_vol, vol)
            if price_id == len(prices):
                raise ValueError(f'Tried to buy {vol} shares, but there is not enough shares to buy')
            price = prices[price_id]
            action = (self.buy_side, vol, price)

        elif 5 <= action_id < 10:
            vol = self.vol * (action_id - 4)
            vols = [obs['bv0'], obs['bv1'], obs['bv2'], obs['bv3'], obs['bv4']]
            prices = [obs['bp0'], obs['bp1'], obs['bp2'], obs['bp3'], obs['bp4']]
            cum_vol = np.cumsum(vols)
            price_id = bisect.bisect_left(cum_vol, vol)
            if price_id == len(prices):
                raise ValueError(f'Tried to sell {vol} shares, but there is not enough shares to sell')
            price = prices[price_id]
            action = (self.sell_side, vol, price)
        elif action_id == 10:
            action = (self.noop_side, 0., 0.)
        else:
            raise ValueError(f'model output should between [0, {self.get_output_shape()})')
        return action

    def select_action(self, observation, model_input: torch.Tensor) -> Tuple[ActionType, torch.tensor, torch.tensor]:
        # 0. inference
        with torch.no_grad():
            model_output = self.model(model_input)
        # 1. postprocess output
        action = self.action_id_to_action(model_output.argmax(-1).item(), observation)

        self._refresh_count += 1
        if self._refresh_count % self.refresh_model_steps == 0:
            self.refresh_model()

        return action, model_input, model_output

    def random_action(self, observation, model_input) -> Tuple[ActionType, torch.tensor, torch.tensor]:
        action_id = random.randrange(0, 11)
        action = self.action_id_to_action(action_id, observation)
        model_output = torch.zeros(11, dtype=torch.float)
        model_output[action_id] = 1
        return action, model_input, model_output
