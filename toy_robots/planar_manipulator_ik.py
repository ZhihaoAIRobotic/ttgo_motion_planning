'''
    Copyright (c) 2022 Idiap Research Institute, http://www.idiap.ch/
    Written by Suhan Shetty <suhan.shetty@idiap.ch>,
   
    This file is part of TTGO.

    TTGO is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License version 3 as
    published by the Free Software Foundation.

    TTGO is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with TTGO. If not, see <http://www.gnu.org/licenses/>.
'''

import torch
import numpy as np
import sys
sys.path.append('../')

from planar_manipulator import PlanarManipulator
from cost_utils import PlanarManipulatorCost
from utils import test_ttgo
from ttgo import TTGO
import time

np.set_printoptions(precision=4, suppress=True)
torch.set_printoptions(precision=4)

import argparse

if __name__ == '__main__':

    ############################################################

    parser = argparse.ArgumentParser()
    parser.add_argument('--d0_x', type=float, default=100)
    parser.add_argument('--d0_theta',type=int, default=50)
    parser.add_argument('--rmax', type=int, default=500)  # max tt-rank for tt-cross
    parser.add_argument('--nswp', type=int, default=30)  # number of sweeps in tt-cross
    parser.add_argument('--margin',type=float, default=0.025)
    parser.add_argument('--b_goal', type=float, default=0.1)
    parser.add_argument('--b_obst', type=float, default=0.1)
    parser.add_argument('--b_orient', type=float, default=1.)

    parser.add_argument('--kr', type=int, default=5)
    parser.add_argument('--w_goal',type=float, default=0.4)
    parser.add_argument('--w_obst',type=float, default=0.4)
    parser.add_argument('--w_orient', type=float, default=0.2)

    parser.add_argument('--n_joints',type=int, default=4)
  
    args = parser.parse_args()
   
    file_name = "planar-ik-n_joints-{}-margin-{}-d0_x-{}-d0_theta-{}-nswp-{}-rmax-{}-kr-{}-b-{}-{}-{}.pickle".format(args.n_joints,
        args.margin,args.d0_x, args.d0_theta, args.nswp, args.rmax, args.kr, args.b_goal, args.b_obst,args.b_orient)
    print(file_name)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("device is ", device)
   
    ############################################################

    # Setup the robot and the environment
    n_joints = args.n_joints
    link_lengths = torch.tensor([1./n_joints]*n_joints).to(device)
    max_theta = np.pi/1.1
    min_theta = -1*max_theta
    robot = PlanarManipulator(n_joints=n_joints,link_lengths=link_lengths,
        max_theta=max_theta,n_kp=10, device=device)    

    # Define the cost and pdf
    x_obst = [torch.tensor([0.5,0.5]),torch.tensor([-0.35,0.]),
    torch.tensor([-0.25,0.75]),torch.tensor([0,-0.75])]
    x_obst = [x_.to(device) for x_ in x_obst]
    r_obst = [0.25,0.15,0.25,0.3]

    costPlanarManipulator = PlanarManipulatorCost(robot,x_obst=x_obst,r_obst=r_obst,
        margin=args.margin,w_goal=args.w_goal,w_obst=args.w_obst,w_orient=args.w_orient,
        b_goal=args.b_goal,b_obst=args.b_obst,b_orient=args.b_orient, device=device)
   
    def cost(x):
        return costPlanarManipulator.cost_ik(x)[:,0]

    def cost_to_print(x): # for printing purposes
        return costPlanarManipulator.cost_ik(x)

    def pdf(x):
        return torch.exp(-cost(x)**2)

    #########################################################
    # Discretize the domain
        
    # Define the range of target poses of the end-effector
    pose_max = torch.sum(link_lengths)
    pose_min = -1*pose_max
    # Discretize

    domain_task=  [torch.linspace(pose_min,pose_max,args.d0_x)]*2 
    domain_decision = [torch.linspace(min_theta,max_theta,args.d0_theta)]*args.n_joints
    domain =  domain_task + domain_decision 

    print("Discretization: ",[len(x) for x in domain])

    #########################################################
    # Fit TT-Model
    ttgo = TTGO(domain=domain,pdf=pdf, cost=cost, device=device)
    ttgo.cross_approximate(rmax=args.rmax, nswp=args.nswp, kickrank=args.kr)

    #########################################################
    # Generate test set (feasible target points)
    ns = 1000
    test_theta = torch.zeros(ns,n_joints).to(device)
    for i in range(n_joints):
        unif = torch.distributions.uniform.Uniform(low=min_theta,high=max_theta)
        sample = torch.tensor([unif.sample() for i in range(ns)])
        test_theta[:,i] = sample
    _, _, test_x, _ = robot.forward_kin(test_theta)
    test_set = torch.cat((test_x,test_theta),dim=-1)
    cost_values = costPlanarManipulator.cost_ik(test_set)
    test_set = test_set[cost_values[:,0]<0.1]
    ns = min(test_set.shape[0],50)
    test_task = test_set[:ns,:2]

    ##########################################################
    # Save the model
    torch.save({
    'ttgo_motion_planning':ttgo,
    'w': (args.w_goal,args.w_obst),
    'b': (args.b_goal,args.b_obst),
    'margin': args.margin,
    'domain': domain,
    'test_task': test_task,
    'n_joints':n_joints
    }, file_name)

    ############################################################ 
    print("############################")
    print("Test the model")
    print("############################")
    sites_task = list(range(len(domain_task)))
    ttgo.set_sites(sites_task)

    norm = 1
    for alpha in [0.99,0.9,0.8,0.5]:
        for n_samples_tt in [10,50,100,1000]:
            test_ttgo(ttgo=ttgo.clone(), cost=cost_to_print, 
                test_task=test_task, n_samples_tt=n_samples_tt,
                alpha=alpha, norm=norm, device=device, test_rand=True)
  ############################################################ 
