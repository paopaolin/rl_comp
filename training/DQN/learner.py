import abc
import copy
from dataclasses import dataclass
from typing import Optional

import torch
import torch.nn.functional as F
from torch import nn

from training.replay.ReplayBuffer import ReplayBuffer
from training.util.torch_device import auto_get_device


@dataclass
class LearnerConfig:
    batch_size: int = 128
    gamma: float = 0.99
    tau: float = 0.005
    lr: float = 1e-4
    optimizer_type = 'SGD'
    device: torch.device = auto_get_device()


class Learner(abc.ABC):
    @abc.abstractmethod
    def step(self) -> Optional[float]:
        pass


class DQNLearner(Learner):
    def __init__(
            self,
            config: LearnerConfig,
            model: nn.Module,
            replay_buffer: ReplayBuffer,
    ):
        self.config = config
        self.replay_buffer = replay_buffer
        self.model = model.to(config.device)
        self.target_model = copy.deepcopy(model).to(config.device)
        self.optimizer = self.__get_optimizer()

    def __get_optimizer(self):
        if self.config.optimizer_type == 'AdamW':
            optimizer = torch.optim.AdamW(self.model.parameters(), lr=self.config.lr)
        elif self.config.optimizer_type == 'Adam':
            optimizer = torch.optim.Adam(self.model.parameters(), lr=self.config.lr)
        elif self.config.optimizer_type == 'SGD':
            optimizer = torch.optim.SGD(self.model.parameters(), lr=self.config.lr)
        else:
            raise ValueError(f'Unknown optimizer type: {self.config.optimizer_type}')
        return optimizer

    def step(self) -> Optional[float]:
        """
        Run a single optimization step of a batch.
        """
        if len(self.replay_buffer.memory) < self.config.batch_size:
            return None

        transitions = self.replay_buffer.sample(self.config.batch_size)
        state, model_output, reward, next_state, done = zip(*transitions)

        state_batch = torch.stack(state).to(self.config.device)
        action_batch = torch.stack(model_output).argmax(1).unsqueeze(1).to(self.config.device)
        reward_batch = torch.tensor(reward).to(self.config.device)
        next_state_batch = torch.stack(next_state).to(self.config.device)
        done_batch = torch.tensor(done).to(self.config.device)

        non_final_mask = done_batch != 0
        non_final_next_states = next_state_batch[non_final_mask]

        # Q(s_t, a)
        state_action_values = self.model(state_batch).gather(1, action_batch)

        # V(s_{t+1}) = max_a Q(s_{t+1}, a)
        next_state_values = torch.zeros(self.config.batch_size, device=self.config.device)
        with torch.no_grad():
            next_state_values[non_final_mask] = self.target_model(non_final_next_states).max(1)[0].detach()
        # expected Q values
        expected_state_action_values = (next_state_values * self.config.gamma) + reward_batch

        # Huber loss
        loss = F.smooth_l1_loss(state_action_values, expected_state_action_values.unsqueeze(1))

        # optimize
        self.optimizer.zero_grad()
        loss.backward()
        # grad clipping
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 100)
        self.optimizer.step()

        return loss.item()

    def update_target_model(self):
        target_params = self.target_model.state_dict()
        params = self.model.state_dict()

        for k in target_params.keys():
            target_params[k] = (1 - self.config.tau) * target_params[k] + self.config.tau * params[k]

        self.target_model.load_state_dict(target_params)