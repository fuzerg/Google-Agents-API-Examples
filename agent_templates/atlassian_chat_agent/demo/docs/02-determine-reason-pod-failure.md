title: Determine the Reason for Pod Failure
source: https://kubernetes.io/docs/tasks/debug/debug-application/determine-reason-pod-failure/
---
This page shows how to write and read a container termination message.

Termination messages provide a way for containers to write information about
fatal events to a location where it can be easily retrieved and surfaced by
tools like dashboards and monitoring software. In most cases, information that
you put in a termination message should also be written to the general
Kubernetes logs.

## Reading a termination message

After a container terminates, inspect its status. The output includes the
container's last state, exit code, and any termination message:

```shell
kubectl get pod termination-demo --output=yaml
```

The relevant portion of the output looks like this:

```yaml
lastState:
  terminated:
    containerID: ...
    exitCode: 0
    finishedAt: ...
    message: |
      Sleep expired
```

You can use a Go template to filter the output so that it includes only the
termination message:

```shell
kubectl get pod termination-demo -o go-template="{{range .status.containerStatuses}}{{.lastState.terminated.message}}{{end}}"
```

For a multi-container Pod, include the container's name so you can discover which
container is failing:

```shell
kubectl get pod multi-container-pod -o go-template='{{range .status.containerStatuses}}{{printf "%s:\n%s\n\n" .name .lastState.terminated.message}}{{end}}'
```

## Customizing the termination message

Kubernetes retrieves termination messages from the file specified in the
`terminationMessagePath` field of a container, which defaults to
`/dev/termination-log`. By customizing this field you can tell Kubernetes to use
a different file. Kubernetes uses the contents of the specified file to populate
the container's status message on both success and failure.

The termination message is intended to be a brief final status, such as an
assertion failure message. The kubelet truncates messages longer than 4096
bytes. The total message length across all containers is limited to 12KiB,
divided equally among each container.

You can set `terminationMessagePath` in the Pod spec:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: msg-path-demo
spec:
  containers:
  - name: msg-path-demo-container
    image: debian
    terminationMessagePath: "/tmp/my-log"
```

## Falling back to logs on error

You can set the `terminationMessagePolicy` field of a container for further
customization. This field defaults to `File`, which means termination messages
are retrieved only from the termination message file. By setting
`terminationMessagePolicy` to `FallbackToLogsOnError`, you tell Kubernetes to
use the **last chunk of container log output** if the termination message file
is empty and the container exited with an error. The log output is limited to
2048 bytes or 80 lines, whichever is smaller.

This is especially useful for diagnosing a container that crashes without writing
an explicit termination message: the kubelet surfaces the tail of its logs in
the Pod status.

## Related concepts

- Exit codes and container states are reported under `.status.containerStatuses`
  (see `state` and `lastState`).
- `ImagePullBackOff` indicates the kubelet could not pull the container image.
- Learn about Pod phase and container states in the Pod lifecycle documentation.
