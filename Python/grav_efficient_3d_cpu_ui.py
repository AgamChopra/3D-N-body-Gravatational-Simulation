import pygame
from torch import cat, nan_to_num, sum, ones, einsum, sqrt, randint
from torch import float64, int64, stack, tensor, sort, clip, no_grad
from math import sin, cos, pi
from time import time
from psutil import cpu_percent

pygame.init()

N = 400
G = 1E-1  # 6.67430E-11
DISPLAYINTERVAL = 3  # render the screen after every n engine steps
SPF = 0.3E-2  # step per frame
RADIUS = 500
TRAIL = 5

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
WIDTH = 1900
HEIGHT = 1080
SCREEN = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.display.set_caption('3D Gravity Simulator Efficient cpu')
FONT = pygame.font.SysFont("Arial", 18, bold=True)
clock = pygame.time.Clock()

EPSILON = 1E0

CAM, F, TRANS, ROT = [int(WIDTH/2), int(HEIGHT/2),
                      0], 1000, [0, 0, 200], [0., 0., 0.]


def event_handler(event):
    global TRANS, ROT, CAM, BH

    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_b:
            CAM, TRANS, ROT = [int(WIDTH/2), int(HEIGHT/2),
                               0], [0, 0, 100], [0, 0, 0]

    keys = pygame.key.get_pressed()

    if keys[pygame.K_w]:
        TRANS[2] -= 6E-1
    if keys[pygame.K_s]:
        TRANS[2] += 6E-1
    if keys[pygame.K_a]:
        TRANS[0] += 6E-1
    if keys[pygame.K_d]:
        TRANS[0] -= 6E-1
    if keys[pygame.K_q]:
        TRANS[1] -= 6E-1
    if keys[pygame.K_e]:
        TRANS[1] += 6E-1

    if keys[pygame.K_k]:
        ROT[0] -= pi * 1E-2
    if keys[pygame.K_i]:
        ROT[0] += pi * 1E-2
    if keys[pygame.K_l]:
        ROT[1] += pi * 1E-2
    if keys[pygame.K_j]:
        ROT[1] -= pi * 1E-2
    if keys[pygame.K_u]:
        ROT[2] -= pi * 1E-2
    if keys[pygame.K_o]:
        ROT[2] += pi * 1E-2


def get_scale(R, Z):
    scale = R / ((Z - CAM[2]) ** 2)
    if scale < 1:
        scale = 1
    if scale > 100:
        scale = 100
    return scale


def fps_counter(tickrate):
    cpu_usage = cpu_percent()
    c = "RED" if cpu_usage > 60 else "YELLOW" if cpu_usage > 20 else "GREEN"
    fps_t = FONT.render(f'cpu(Ryzen5 5500): {cpu_usage}%', 1, pygame.Color(c))
    SCREEN.blit(fps_t, (int(WIDTH/2.2), 60))

    flag = int(clock.get_fps())
    c = "RED" if flag < 15 else "YELLOW" if flag < 30 else "GREEN"
    fps = f'Display FPS: {flag}'
    fps_t = FONT.render(fps, 1, pygame.Color(c))
    SCREEN.blit(fps_t, (int(WIDTH/2.2), 80))

    c = "RED" if tickrate < 30 else "YELLOW" if tickrate < 60 else "GREEN"
    fps = f'Engine tickrate: {int(tickrate)}'
    fps_t = FONT.render(fps, 1, pygame.Color(c))
    SCREEN.blit(fps_t, (int(WIDTH/2.2), 100))


def draw_window(compute_matrix, color, lighting, tickrate):
    x_all = proj_3_to_2(
        CAM, compute_matrix[:, :3], F, TRANS, ROT).to(dtype=int64)
    x_ = x_all[-N:]
    x_trail = x_all.view((int(x_all.shape[0]/N)), N, 3).permute(1, 0, 2)
    display_matrix = cat((x_, color), axis=1)
    SCREEN.fill(lighting)
    _, idx = sort(display_matrix[:, 2], descending=True)

    for i, cell in enumerate(display_matrix[idx].numpy()):
        if cell[2] > CAM[2]:
            if len(x_trail[i]) > 1:
                trail_points = [(int(p[0]), int(p[1])) for p in x_trail[i]]
                pygame.draw.lines(SCREEN, [60, 50, 70],
                                  False, trail_points, 1)
            pygame.draw.circle(SCREEN, [cell[3], cell[4], cell[5]],
                               (cell[0], cell[1]), get_scale(RADIUS, cell[2]))

    fps_counter(tickrate)
    pygame.display.update()


def norm(X):
    return (X - min(X))/(max(X) - min(X))


class FixedQueueTensor:
    def __init__(self, max_size=TRAIL, shape=(N, 9)):
        self.max_size = max_size
        self.shape = shape
        self.queue = ones((0, *shape))

    def append(self, element):
        self.queue = cat((self.queue, element.unsqueeze(0)), dim=0)

        if self.queue.shape[0] > self.max_size:
            self.queue = self.queue[1:]

    def get_tensor(self):
        return self.queue


def decay(M1, M2, v, r):
    return 1E-14 * v * ((M1 * M2) / r**2)


def check_merger(x, M, N, v, color):
    r_ = sum((x[int(3*N/4)] - x[int(N/4)]) ** 2)**(1/2)

    if r_ <= SPF * 1E2:
        M[int(N/4)] += M[int(3*N/4)]
        M[int(3*N/4)] = 0
        v[int(N/4)] *= 0
        v[int(3*N/4)] *= 1E4
        x[int(N/4)] = (x[int(N/4)] + x[int(3*N/4)])/2
        color[int(3*N/4)] *= 0

    else:
        v[int(N/4)] = v[int(N/4)] - decay(M[int(N/4)],
                                          M[int(3*N/4)], v[int(N/4)], r_)
        v[int(3*N/4)] = v[int(3*N/4)] - decay(M[int(3*N/4)],
                                              M[int(N/4)], v[int(3*N/4)], r_)
    return M, v, x, color


def get_rot_matx(psi, theta, phi):
    r11 = cos(theta) * cos(phi)
    r12 = sin(psi) * sin(theta) * cos(phi) - cos(psi) * sin(phi)
    r13 = cos(psi) * sin(theta) * cos(phi) + sin(psi) * sin(phi)

    r21 = cos(theta) * sin(phi)
    r22 = sin(psi) * sin(theta) * sin(phi) + cos(psi) * cos(phi)
    r23 = cos(psi) * sin(theta) * sin(phi) - sin(psi) * cos(phi)

    r31 = -sin(theta)
    r32 = sin(psi) * cos(theta)
    r33 = cos(psi) * cos(theta)

    return [r11, r12, r13, r21, r22, r23, r31, r32, r33]


def proj_3_to_2(cam_coord, obj_coord, f, trans, rot_ang):
    r = get_rot_matx(rot_ang[0], rot_ang[1], rot_ang[2])

    obj_1 = ones(obj_coord.shape[0], 1).to(dtype=float64)

    X = cat((obj_coord, obj_1), dim=1).T
    K = tensor(((f, 0, cam_coord[0]), (0, f, cam_coord[1]), (0, 0, 1))).to(
        dtype=float64)
    E = tensor(((r[0], r[1], r[2], trans[0]), (r[3], r[4], r[5], trans[1]),
               (r[6], r[7], r[8], trans[2]))).to(dtype=float64)

    X_ = K @ E @ X

    x = X_[0]/X_[2]
    y = X_[1]/X_[2]
    lam = X_[2]

    return stack((x, y, lam), dim=1)


def newtonian_gravitational_dynamics(compute_matrix, counter, M, color,
                                     SPF=1/144, WIDTH=600, HEIGHT=600, N=2000):
    x = compute_matrix[:, :3]
    y = x.reshape(x.shape[0], 1, x.shape[1])

    R = sqrt(einsum('ijk, ijk->ij', x-y, x-y))
    M_ = M @ M.T
    R_ = stack([(x - x[i]) / (R[i].reshape(R.shape[0], 1) + EPSILON)
               for i in counter], dim=0)

    a = sum(nan_to_num((1/(M * ones((R.shape[0], R.shape[0])))) * G * (
        M_/((R ** 2) + EPSILON))).reshape(R.shape[0], R.shape[0], 1) * R_,
        axis=1)
    v = compute_matrix[:, 3:6] + (a * SPF)
    x = x + (v * SPF)

    if M[int(3*N/4)] > 0:
        M, v, x, color = check_merger(x, M, N, v, color)

    # Outputs
    compute_matrix = cat((x, v, a), axis=1)

    return compute_matrix, M, color


def main():
    with no_grad():
        global CAM, HEIGHT, WIDTH
        run = True

        M = randint(int(10), int(30), (N, 1)).to(dtype=float64) * 500

        width = cat((randint(-30, -25, (int(N/2), 1)), randint(25,
                    30, (int(N/2), 1))), dim=0).to(dtype=float64)
        depth = cat((randint(-2, 2, (int(N/2), 1)), randint(-2, 2,
                    (int(N/2), 1))), dim=0).to(dtype=float64)
        height = cat((randint(-100, -95, (int(N/2), 1)), randint(95,
                     100, (int(N/2), 1))), dim=0).to(dtype=float64)

        vx = randint(-2, 2, (N, 1)).to(dtype=float64)
        vz = randint(-2, 2, (N, 1)).to(dtype=float64)
        vy = cat((randint(40, 50, (int(N/2), 1)), randint(-50, -40,
                 (int(N/2), 1))), dim=0).to(dtype=float64)

        color = cat((clip(100 + 1.00034 ** M, 0, 200),
                     clip(-150 + 1.00037 ** M, 0, 175),
                     clip(-50 + 1.0003772 ** M, 0, 225)),
                    dim=1).to(dtype=int64)

        for i in randint(0, N, (int(N/20),)):
            M[i] = 7 * 1E1 * randint(1, 100, ())
            color[i] *= 0
            color[i] += 255

        M[int(N/4)] = 8E4*10
        M[int(3*N/4)] = 7.7E4*10

        color[int(N/4)] *= 0
        color[int(3*N/4)] *= 0
        color[int(N/4), 1] += 255
        color[int(3*N/4), 1] += 255

        width[int(N/4)] = -10
        width[int(3*N/4)] = 10
        depth[int(N/4)] = 0
        depth[int(3*N/4)] = 0
        height[int(N/4)] = -70
        height[int(3*N/4)] = 70

        vy[int(N/4)] = 5
        vy[int(3*N/4)] = -5

        compute_matrix = cat(
            (width, height, depth, vx, vy, vz, vx*0., vy*0., vz*0.), axis=1)
        print(compute_matrix.shape)

        time_step = 1
        lighting = BLACK
        counter = range(N)
        start_time = time()

        log = FixedQueueTensor()
        log.append(compute_matrix)

        while run:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    run = False

                event_handler(event)

            compute_matrix, M, color = newtonian_gravitational_dynamics(
                compute_matrix, counter, M=M, color=color, WIDTH=WIDTH,
                HEIGHT=HEIGHT, SPF=SPF, N=N)

            if time_step % DISPLAYINTERVAL == 0:

                # Camera
                ROT[1] += pi * 3E-3
                TRANS[2] -= 5E-4

                log.append(compute_matrix)
                fps = 1 / (time() - start_time)
                tickrate = DISPLAYINTERVAL * fps
                clock.tick(fps)
                start_time = time()

                draw_window(log.queue.view(
                    N*log.queue.shape[0], 9), color, lighting, tickrate)

            time_step += 1

        pygame.quit()


if __name__ == '__main__':
    main()
