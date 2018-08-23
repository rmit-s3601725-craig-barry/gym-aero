import simulation.quadrotor3 as quad
import simulation.config as cfg
import simulation.animation as ani
import matplotlib.pyplot as pl
import numpy as np
import random
from math import pi, sin, cos
import gym
from gym import error, spaces, utils
from gym.utils import seeding

#Defines the sigmoid function:
# formally:
#
# y = 1 / (1 + e^-x)
def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x));

#Converts numpy vectors to a list
def npl(np_vec):
    return np_vec.T.tolist()[0];
"""
    Environment wrapper for a hover task. The goal of this task is for the agent to climb from [0, 0, 0]^T
    to [0, 0, 1.5]^T, and to remain at that altitude until the the episode terminates at T=15s.
"""

class TargetFollowingEnv(gym.Env):
    def __init__(self):
        metadata = {'render.modes': ['human']}

        # environment parameters
        self.goal_xyz = np.array([[2.0],
                                [1.5],
                                [0.0]])
        self.start_pos = np.array([[0.0],
                                [0.0],
                                [0.0]])

        self.goal_zeta_sin = np.sin(np.array([[0.],
                                            [0.],
                                            [0.]]))
        self.goal_zeta_cos = np.cos(np.array([[0.],
                                            [0.],
                                            [0.]]))
        self.goal_uvw = np.array([[0.],
                                [0.],
                                [0.]])
        self.goal_pqr = np.array([[0.],
                                [0.],
                                [0.]])

        #Sets the xyz dimensions of the environment
        self.x_dim = 6;
        self.y_dim = 6;
        self.z_dim = 4;

        #The current running time (in seconds) of the simulation
        self.t = 0
        #The total maximum time of the simulation
        self.T = 25
        #The number of action input parameters
        self.num_actions = 4;
        #The number of input options
        self.action_space = np.zeros((self.num_actions,))
        #The number of values that pertain to the current state of the agent
        self.nStateVals = 22;
        #The number of goal values
        self.nGoals = 1;
        #The total number of values that pertain to an observation (given state)
        self.observation_space = np.zeros((self.nStateVals+self.num_actions+self.nGoals,));

        # simulation parameters
        self.params = cfg.params
        self.iris = quad.Quadrotor(self.params)
        self.sim_dt = self.params["dt"]
        self.ctrl_dt = 0.05
        self.steps = range(int(self.ctrl_dt/self.sim_dt))
        self.action_bound = [0, self.iris.max_rpm]
        self.H = int(self.T/self.ctrl_dt)
        self.hov_rpm = self.iris.hov_rpm
        self.trim = [self.hov_rpm, self.hov_rpm,self.hov_rpm, self.hov_rpm]
        self.trim_np = np.array(self.trim)
        self.bandwidth = 35.

        self.iris.set_state(self.start_pos, np.arcsin(self.goal_zeta_sin), self.goal_uvw, self.goal_pqr)
        xyz, zeta, uvw, pqr = self.iris.get_state()

        self.vec_xyz = xyz-self.start_pos
        self.vec_zeta_sin = np.sin(zeta)-self.goal_zeta_sin
        self.vec_zeta_cos = np.cos(zeta)-self.goal_zeta_cos
        self.vec_uvw = uvw-self.goal_uvw
        self.vec_pqr = pqr-self.goal_pqr

        self.fig = None
        self.axis3d = None
        self.v = None

    def reward(self, state, action, terminal):
        xyz, zeta, uvw, pqr = state
        
        s_zeta = np.sin(zeta)
        c_zeta = np.cos(zeta)

        curr_dist = xyz-self.goal_xyz
        curr_att_sin = s_zeta-self.goal_zeta_sin
        curr_att_cos = c_zeta-self.goal_zeta_cos
        curr_vel = uvw-self.goal_uvw
        curr_ang = pqr-self.goal_pqr
        
        # magnitude of the distance from the goal 
        dist_hat = np.linalg.norm(curr_dist)
        att_hat_sin = np.linalg.norm(curr_att_sin)
        att_hat_cos = np.linalg.norm(curr_att_cos)
        vel_hat = np.linalg.norm(curr_vel)
        ang_hat = np.linalg.norm(curr_ang)

        #Store unweighted reward values for visualization & debugging
        self.dist_rew = self.dist_reward(self.goal_dist, dist_hat);
        self.height_rew = self.dist_reward(xyz[2][0], self.goal_xyz[2][0]);

        #Agent receives reward for maintaining the set distance from the goal
        dist_rew = 200 * (self.dist_rew - 0.5);
        #Agent receives reward for maintaining a similar height to the goal
        height_rew = 70 * (self.height_rew - 0.5);
        #Agent receives a higher reward the longer it is alive
        # time_rew = max(10 * self.t, 50);
        time_rew = 30 * self.t;
        #Agent receives a bad reward for dying (to prevent dive-bombing close to goal)
        term_rew = -10000 if (terminal and self.t < self.T) else 0;

        height_rew = 0;
        
        self.vec_xyz = curr_dist
        self.vec_zeta_sin = curr_att_sin
        self.vec_zeta_cos = curr_att_cos
        self.vec_uvw = curr_vel
        self.vec_pqr = curr_ang

        # print(dist_rew);
        # print(height_rew);

        return dist_rew, height_rew, time_rew, term_rew;

    def dist_reward(self, goal_dist, dist):
        """
            The distance reward is calculated using the derivate of the sigmoid function,
            where the peak is the goal distance. i.e. where s is the sigmoid function and
            g is the goal distance, the reward function is calculated as:

            dy/dx = s(x - g) * (1 - s(x - g))

            This function asymptotes to 0 on x approaches +inf and -inf and peaks
            at x = goal_dist with a y value of 0.25, the result will be multiplied by 4
            to get a nice value between 0 and 1
        """

        #With a constant multiplier of 4, the function will now return a value between 0 & 1
        constMultiplier = 4;
        #The error between current distance and goal distance
        x = dist - goal_dist;
        #Calculate reward
        reward = sigmoid(x) * (1.0 - sigmoid(x));
        #Multiply reward by constant multiplier
        return (constMultiplier * reward);

    def terminal(self, pos):
        xyz, zeta = pos
        mask1 = 0#zeta > pi/2
        mask2 = 0#zeta < -pi/2
        mask3 = (np.abs(xyz[0]) > self.x_dim or
            np.abs(xyz[1]) > self.y_dim or
            np.abs(xyz[2]) > self.z_dim);
        if np.sum(mask1) > 0 or np.sum(mask2) > 0 or np.sum(mask3) > 0:
            return True
        elif self.t >= self.T:
            print("Sim time reached")
            return True
        else:
            return False

    def step(self, action):
        """
            TODO

            -   Add to observation space:
                    -> The velocity of the goal after adding non-determinisim
                    -> The relative velocity of the agent to the goal
        """

        for _ in self.steps:
            xyz, zeta, uvw, pqr = self.iris.step(self.trim_np+action*self.bandwidth)
        sin_zeta = np.sin(zeta)
        cos_zeta = np.cos(zeta)
        a = (action/self.action_bound[1]).tolist()

        last_goal_xyz = self.goal_xyz;
        #Set the goal's position
        self.goal_xyz = self.move_goal(self.t + self.ctrl_dt);
        #Calculate goal velocity from last 2 known positions
        self.goal_veloc = self.goal_xyz - last_goal_xyz;
        #Calculate the vector to the goal
        vec_to_goal = self.goal_xyz - xyz;
        #the position of the goal
        self.dist_to_goal = np.linalg.norm(vec_to_goal);
        #normalize vector to goal
        self.vec_to_goal = vec_to_goal / self.dist_to_goal;
        #Calculat the relative inertial velocity from the agent's velocity to the goal's velocity
        self.rel_inertial_vel = self.iris.get_inertial_velocity() + self.goal_veloc;
        #Calculate the position of maximum distance reward on the vector between the agent and the goal
        self.closest_goal_pos = self.vec_to_goal * (self.dist_to_goal - self.goal_dist);

        #Get the values that correspond to the current state of the agent
        #if the given action is 
        # next_state = npl(xyz)+npl(sin_zeta)+npl(cos_zeta)+npl(uvw)+npl(pqr)+npl(vec_to_goal)+[dist_to_goal];
        next_state = npl(xyz)+npl(sin_zeta)+npl(cos_zeta)+npl(uvw)+npl(pqr)+npl(vec_to_goal)+[self.dist_to_goal];
        #Calculate whether the agent is in a terminal state
        done = self.terminal((xyz, zeta))
        #Get the information that pertains to the new state
        info = self.reward((xyz, zeta, uvw, pqr), action, done)
        #Get the reward for this state
        reward = sum(info)
        #Get the current goals for this state
        goals = [self.goal_dist] + npl(self.closest_goal_pos);
        #Add the goals and actions to the current state
        next_state = next_state+a+goals;
        #Increment the current time
        self.t += self.ctrl_dt

        return next_state, reward, done, info

    def move_goal(self, t):
        """
            TODO:

            -   Create a moving goal that moves non-deterministicly through the container
                without coming too close to walls
        """
        return np.array([[2.0 + sin(self.t * 2.0)],
                        [0.0],
                        [1.5 + cos(self.t * 2.0)]])

    def reset(self):
        self.t = 0.
        self.iris.set_state(self.start_pos, np.sin(self.goal_zeta_sin), self.goal_uvw, self.goal_pqr)
        xyz, zeta, uvw, pqr = self.iris.get_state()
        sin_zeta = np.sin(zeta)
        cos_zeta = np.cos(zeta)
        self.vec_xyz = xyz-self.start_pos
        self.vec_zeta_sin = sin_zeta-self.goal_zeta_sin
        self.vec_zeta_cos = cos_zeta-self.goal_zeta_cos
        self.vec_uvw = uvw-self.goal_uvw
        self.vec_pqr = pqr-self.goal_pqr
        a = [x/self.action_bound[1] for x in self.trim]

        #Initial goal velocity is nothing, as it hasn't moved yet
        self.goal_veloc = np.array([[0.],
                                    [0.],
                                    [0.]]);
        #Initial relative intertial velocity is nothing, as neither agent nor goal is moving
        self.rel_inertial_vel = np.array([[0.],
                                    [0.],
                                    [0.]]);
        #Reset the goal position
        self.goal_xyz = self.move_goal(self.t);
        #Calculates the distance between the goal and the starting position of the quadrotor
        self.goal_dist = np.linalg.norm(self.start_pos - self.goal_xyz);
        #Calculate the vector to the goal
        vec_to_goal = xyz-self.goal_xyz;
        #the position of the goal
        self.dist_to_goal = np.linalg.norm(vec_to_goal);
        #normalize vector to goal
        vec_to_goal = vec_to_goal / self.dist_to_goal;
        #Initialize best goal position at start to agent's position
        self.closest_goal_pos = self.start_pos;

        #Get the initial goal state
        goals = [self.goal_dist] + npl(self.closest_goal_pos);
        #Get the initial state of the agent
        # state = npl(xyz)+npl(sin_zeta)+npl(cos_zeta)+npl(uvw)+npl(pqr)+npl(vec_to_goal)+[dist_to_goal];+npl(self.rel_inertial_vel)
        state = npl(xyz)+npl(sin_zeta)+npl(cos_zeta)+npl(uvw)+npl(pqr)+npl(vec_to_goal)+[self.dist_to_goal];
        #Combine the goals, actions and state values to represent the entire agent initial state
        state = state+a+goals;
        return state;

    def bezier(self, start, end, control, t):
        t_inv = 1.0 - t;
        return t_inv*(t_inv*start + t*control) + t*(t_inv*control + t*end);
    
    def render(self, mode='human', close=False):
        """
            TODO

            -   Perform rendering using pyglet and OpenGL
            -   Allow recording/playback of simulation
        """

        if self.fig is None:
            # rendering parameters
            pl.close("all")
            pl.ion()
            self.fig = pl.figure("Target Following")
            self.axis3d = self.fig.add_subplot(111, projection='3d')
            self.vis = ani.Visualization(self.iris, 6, quaternion=True)

        pl.figure("Target Following")

        self.axis3d.cla()
        #Draw the quadrotor
        self.vis.draw3d_quat(self.axis3d)
        #Draw the goal point
        self.vis.draw_goal(self.axis3d, self.goal_xyz)
        #Set the limits of the container to the given dimensions
        self.axis3d.set_xlim(-self.x_dim, self.x_dim)
        self.axis3d.set_ylim(-self.y_dim, self.y_dim)
        self.axis3d.set_zlim(-self.z_dim, self.z_dim)
        self.axis3d.set_xlabel('West/East [m]')
        self.axis3d.set_ylabel('South/North [m]')
        self.axis3d.set_zlabel('Down/Up [m]')
        self.axis3d.set_title("Time %.3f s" %(self.t))

        #Get the position of the agent
        xyz, _, _, _, = self.iris.get_state();
        #Draw a line between goal and quadrotor, that will be more green depending on how close
        #the distance is to the goal distance to help visualize goal distance
        self.vis.draw_line(self.axis3d, self.goal_xyz.T.tolist()[0], xyz.T.tolist()[0], color=[0,self.dist_rew,0])
        
        self.vis.draw_goal(self.axis3d, xyz + self.closest_goal_pos, color=[0,0,1]);

        self.vis.draw_line(self.axis3d, npl(xyz), npl(xyz + self.vec_to_goal), color=[1,0,0]);

        start_point =  np.array([[2.0],[2.0],[2.0]]);
        control_point = np.array([[2.0],[-2.0],[2.0]]);
        end_point = np.array([[-2.0],[-2.0],[-2.0]]);

        leng = 12;
        for i in range(leng):
            pt = self.bezier(start_point, end_point, control_point, (1.0 / leng) * i);
            self.vis.draw_goal(self.axis3d, pt, color=[1,0,1]);

        self.vis.draw_goal(self.axis3d, start_point, color=[1,1,0]);
        self.vis.draw_goal(self.axis3d, end_point, color=[0,1,0]);
        self.vis.draw_goal(self.axis3d, control_point, color=[1,0,0]);
        #Draw goal velocity
        # self.vis.draw_line(self.axis3d, self.goal_xyz.T.tolist()[0], (self.goal_xyz + (self.goal_veloc * 10)).T.tolist()[0], color=[1,0,0])
        #Draw relative intertial velocity
        # self.vis.draw_line(self.axis3d, xyz.T.tolist()[0], (xyz + self.rel_inertial_vel).T.tolist()[0], color=[0,0,1])

        pl.pause(0.001)
        pl.draw()

