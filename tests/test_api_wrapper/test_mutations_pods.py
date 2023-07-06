import unittest

from runpod.api_wrapper.mutations.pods import generate_pod_deployment_mutation, generate_pod_stop_mutation, generate_pod_resume_mutation, generate_pod_terminate_mutation

class TestPodMutations(unittest.TestCase):
    ''' Test API Wrapper Pod Mutations '''

    def test_generate_pod_deployment_mutation(self):
        '''
        Test generate_pod_deployment_mutation
        '''
        result = generate_pod_deployment_mutation(
            name="test",
            image_name="test_image",
            gpu_type_id="1",
            cloud_type="cloud",
            data_center_id="1",
            country_code="US",
            gpu_count=1,
            volume_in_gb=100,
            container_disk_in_gb=10,
            min_vcpu_count=1,
            min_memory_in_gb=1,
            docker_args="args",
            ports="8080",
            volume_mount_path="/path",
            env={"ENV": "test"},
            support_public_ip=True)

        # Here you should check the correct structure of the result
        self.assertIn("mutation", result)

    def test_generate_pod_stop_mutation(self):
        '''
        Test generate_pod_stop_mutation
        '''
        result = generate_pod_stop_mutation("pod_id")
        # Here you should check the correct structure of the result
        self.assertIn("mutation", result)

    def test_generate_pod_resume_mutation(self):
        '''
        Test generate_pod_resume_mutation
        '''
        result = generate_pod_resume_mutation("pod_id", 1)
        # Here you should check the correct structure of the result
        self.assertIn("mutation", result)

    def test_generate_pod_terminate_mutation(self):
        '''
        Test generate_pod_terminate_mutation
        '''
        result = generate_pod_terminate_mutation("pod_id")
        # Here you should check the correct structure of the result
        self.assertIn("mutation", result)

if __name__ == "__main__":
    unittest.main()
